#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Written with love and care by Carter for Justin
#
# Copyright © 2021 Carter Yagemann <yagemann@protonmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the “Software”), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import print_function

import gzip
import json
import logging
from optparse import OptionParser
import os
import shutil
import sys
from time import sleep

import pixivpy3 as pixiv
import requests

prog_ver = '1.1.0'
prog_use = 'Usage: %prog [-l] [--logging] config ...'

log = logging.getLogger()
log_fmt = '%(levelname)7s | %(asctime)-15s | %(message)s'

class ConfigException(Exception):
    pass

def parse_args():
    """Parses sys.argv"""
    parser = OptionParser(usage=prog_use, version='Pixiv Discord Bot %s' % prog_ver)

    parser.add_option('-l', '--logging', action='store', type='int', default=20,
            help='Log level [10-50] (default: 20 - Info)')

    options, args = parser.parse_args()

    # input validation
    if len(args) < 1:
        print("Must specify at least one configuration file", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    return (options, args)

def search_and_post(api, options, config, history, sub_tag, found_msg, missing_msg):
    """Search for an image that meets the required tags and post it"""
    main_tag = config['main_tag']
    webhooks = config['discord_hook_urls']

    chosen_urls = None
    res = api.search_illust(sub_tag,
            search_target='exact_match_for_tags',
            sort='date_desc')

    if not 'illusts' in res:
        log.error("Failed to search for: %s" % sub_tag)
        return

    for img in res['illusts']:
        debug_url = list(img['image_urls'].values())[-1]

        if not main_tag in [tag['name'] for tag in img['tags']]:
            # main tag and sub tag *must* match, this is how we prevent
            # (for example) fetching character fanart for the wrong
            # character with the same name!
            log.debug("Skipping missing tag: %s" % debug_url)
            continue

        # fetch additional details
        img_detail = api.illust_detail(img['id'])
        if not 'illust' in img_detail:
            continue
        img_detail = img_detail['illust']

        # certain image types based on config
        if not config['allow_R18'] and img_detail['x_restrict'] != 0:
            log.debug("Skipping R18: %s" % debug_url)
            continue

        # we require a large and medium version, the former because we
        # want high quality artwork, the latter as a fallback if the former
        # exceeds Discord's upload limit
        if not 'large' in img['image_urls'].keys():
            log.debug("Skipping for not having a large version: %s" % debug_url)
            continue
        if not 'medium' in img['image_urls'].keys():
            log.debug("Skipping for not having a medium version: %s" % debug_url)
            continue

        # always use large version for checking against the history
        if not img['image_urls']['large'] in history:
            chosen_urls = img['image_urls']
            break

        if not chosen_urls is None:
            break

    if chosen_urls:
        # download image locally
        img_name = os.path.basename(chosen_urls['large'])
        img_path = os.path.join('/tmp', img_name)

        try:
            api.download(chosen_urls['large'], path='/tmp', name=img_name)
        except pixiv.utils.PixivError as ex:
            # Pixiv CDN can sometimes refuse to serve an image, no amount of
            # retries will fix it, add to history so it's skipped in the future
            log.warning("Failed to download URL: %s - %s" % (chosen_urls['large'], str(ex)))
            history.add(chosen_urls['large'])
            return

        # Discord has a 8MB file upload limit. If image is too big, grab the
        # medium version.
        if os.path.getsize(img_path) > 0x800000:
            os.remove(img_path)

            try:
                api.download(chosen_urls['medium'], path='/tmp', name=img_name)
            except pixiv.utils.PixivError as ex:
                # again, Pixiv CDN can permanently refuse to serve some images
                log.warning("Failed to download URL: %s - %s" % (chosen_urls['medium'], str(ex)))
                history.add(chosen_urls['large'])
                return

        # if this is somehow still too large, we're out of luck
        if os.path.getsize(img_path) > 0x800000:
            log.error("medium version of image still too large for Discord, "
                      "cannot upload: %s" % chosen_urls['medium'])
        else:
            # ready to post to Discord
            for webhook in webhooks:
                if len(found_msg) > 0:
                    requests.post(webhook, data={'content': found_msg},
                            files={'file': open(img_path, 'rb')})
            # rate limit
            sleep(5)

        # cleanup
        os.remove(img_path)
        history.add(chosen_urls['large'])

    else:
        # no satisfactory image found
        log.warning("No image found for main tag, sub tag: "
                    "('%s', '%s')" % (main_tag, sub_tag))
        if len(missing_msg) > 0:
            for webhook in webhooks:
                requests.post(webhook, data={'content': missing_msg})

def load_history(history_fp):
    """Load the history file"""
    if os.path.isfile(history_fp):
        with gzip.open(history_fp, 'rt') as ifile:
            return set([l.strip() for l in ifile.readlines()])
    else:
        log.warning("No history file, creating an empty one")
        return set()

def save_history(history_fp, history):
    """Save history to file"""
    assert isinstance(history, set)
    # we use a tempfile so that if this somehow crashes, we don't
    # lose the entire history
    tmp_fp = history_fp + '.tmp'
    with gzip.open(tmp_fp, 'wt') as ofile:
        ofile.write("\n".join(list(history)))
    shutil.move(tmp_fp, history_fp)

def parse_config(config_fp):
    """Parses the config file, returning a dictionary.

    Raises a ConfigException if config is invalid.
    """
    if not os.path.isfile(config_fp):
        error = "File not found: %s" % config_fp
        log.error(error)
        raise ConfigException(error)

    try:
        with open(config_fp) as ofile:
            config = json.load(ofile)
    except Exception as ex:
        error = "Failed to read config: %s" % str(ex)
        log.error(error)
        raise ConfigException(error)

    # validate config file
    required_keys = [('pixiv_username', str), ('pixiv_password', str),
                     ('discord_hook_urls', list), ('main_tag', str),
                     ('sub_tags', list), ('wildcard', bool), ('allow_R18', bool)]

    for key, val_type in required_keys:
        if not key in config:
            error = "Config missing required parameter: %s" % key
            log.error(error)
            raise ConfigException(error)
        if not isinstance(config[key], val_type):
            error = "Config parameter %s must be %s" % (key, str(val_type))
            log.error(error)
            raise ConfigException(error)

    # sub_tag should be a list of 3-tuples
    for tag in config['sub_tags']:
        if len(tag) != 3:
            error = "Each sub-tag must be 3 items: tag, found string, missing string"
            log.error(error)
            raise ConfigException(error)
        for item in tag:
            if not isinstance(item, str):
                error = "All subtag values must be strings: %s" % item
                log.error(error)
                raise ConfigException(error)

    # discord_hook_urls should be a list of strings
    for url in config['discord_hook_urls']:
        if not isinstance(url, str):
            error = "All Discord hook URLs should be strings: %s" % url
            log.error(error)
            raise ConfigException(error)

    return config

def init_logging(level):
    """Initializes root logging facilities"""
    log.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(log_fmt))
    log.addHandler(handler)

def refresh_auth(api, refresh_fp):
    """Pixiv recently removed password authentication. This method implements a workaround
    using a prior refresh token to get a new auth token."""
    if not os.path.isfile(refresh_fp):
        log.error("Pixiv has removed password authentication. As a workaround, you must create "
                  "%s and place a valid refresh token in it. For details, see: "
                  "https://gist.github.com/upbit/6edda27cb1644e94183291109b8a5fde and "
                  "https://github.com/upbit/pixivpy/issues/158" % refresh_fp)
        sys.exit(3)

    with open(refresh_fp, 'r') as ifile:
        token = ifile.read().strip()

    log.debug("Old refresh token: %s" % token)

    api.auth(refresh_token=token)

    log.debug("New refresh token: %s" % api.refresh_token)

    # refresh token doesn't appear to change even after using it, but just in case,
    # we write it back to the file
    with open(refresh_fp, 'w') as ofile:
        ofile.write(api.refresh_token)

def main():
    # parse args and initialize logging
    options, args = parse_args()
    init_logging(options.logging)
    # some important file paths
    root_dir = os.path.dirname(os.path.realpath(__file__))
    history_fp = os.path.join(root_dir, 'history')

    # initialize Pixiv API
    try:
        api = pixiv.AppPixivAPI()
        # Pixiv has removed password authentication, below is a workaround
        # using refresh tokens
        refresh_auth(api, os.path.join(root_dir, 'refresh'))
    except Exception as ex:
        log.error("Failed to initialize Pixiv API: %s" % str(ex))
        sys.exit(1)

    # load history
    history = load_history(history_fp)

    for config_fp in args:
        try:
            config = parse_config(config_fp)
        except ConfigException:
            # parse_config already logged an error message
            continue

        # everybody walk the dinosaur
        for sub_tag in config['sub_tags']:
            try:
                search_and_post(api, options, config, history, *sub_tag)
            except pixiv.utils.PixivError as ex:
                log.error("Pixiv error: %s" % str(ex))

        # wildcard
        if config['wildcard']:
            try:
                search_and_post(api, options, config, history, config['main_tag'],
                        "Today's wildcard is...", "")
            except pixiv.utils.PixivError as ex:
                log.error("Pixiv error: %s" % str(ex))

    # save history
    save_history(history_fp, history)


if __name__ == '__main__':
    main()
