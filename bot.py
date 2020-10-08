#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Written with love and care by Carter for Justin
#
# Copyright © 2020 Carter Yagemann <yagemann@protonmail.com>
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

prog_ver = '1.0.1'
prog_use = 'Usage: %prog [options] <config_file>'

log = logging.getLogger()
log_fmt = '%(levelname)7s | %(asctime)-15s | %(message)s'

def parse_args():
    """Parses sys.argv"""
    parser = OptionParser(usage=prog_use, version='Pixiv Discord Bot %s' % prog_ver)

    parser.add_option('-l', '--logging', action='store', type='int', default=20,
            help='Log level [10-50] (default: 20 - Info)')

    options, args = parser.parse_args()

    # input validation
    if len(args) != 1:
        print("Must specify a configuration file", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    return (options, args)

def search_and_post(api, options, config, history, sub_tag, found_msg, missing_msg):
    """Search for an image that meets the required tags and post it"""
    main_tag = config['main_tag']
    webhooks = config['discord_hook_urls']

    chosen_urls = None
    for page in range(1, 100):
        res = api.search_works(sub_tag, mode='exact_tag', page=page)
        if not 'response' in res:
            # out of pages
            break

        for img in res.response:
            debug_url = list(img['image_urls'].values())[-1]

            if not main_tag in img['tags']:
                # main tag and sub tag *must* match, this is how we prevent
                # (for example) fetching character fanart for the wrong
                # character with the same name!
                log.debug("Skipping missing tag: %s" % debug_url)
                continue

            # certain image types based on config
            if not config['allow_manga'] and img['is_manga']:
                log.debug("Skipping manga: %s" % debug_url)
                continue
            if not config['allow_R18'] and img['age_limit'] == 'r18':
                log.debug("Skipping R18: %s" % debug_url)
                continue
            if not config['allow_R18-G'] and img['age_limit'] == 'r18-g':
                log.debug("Skipping R18-G: %s" % debug_url)
                continue

            # we require a large and px_480mw version, the former because we
            # want high quality artwork, the latter as a fallback if the former
            # exceeds Discord's upload limit
            if not 'large' in img['image_urls'].keys():
                log.debug("Skipping for not having a large version: %s" % debug_url)
                continue
            if not 'px_480mw' in img['image_urls'].keys():
                log.debug("Skipping for not having a px_480mw version: %s" % debug_url)
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
        api.download(chosen_urls['large'], path='/tmp', name=img_name)
        img_path = os.path.join('/tmp', img_name)

        # Discord has a 8MB file upload limit. If image is too big, grab the
        # px_480mw version.
        if os.path.getsize(img_path) > 0x800000:
            os.remove(img_path)
            api.download(chosen_urls['px_480mw'], path='/tmp', name=img_name)

        # if this is somehow still too large, we're out of luck
        if os.path.getsize(img_path) > 0x800000:
            log.error("480mw version of image still too large for Discord, "
                      "cannot upload: %s" % chosen_urls['px_480mw'])
        else:
            # ready to post to Discord
            for webhook in webhooks:
                if len(found_msg) > 0:
                    requests.post(webhook, data={'content': found_msg}, files={'file': open(img_path, 'rb')})
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

def parse_config_or_die(config_fp):
    """Parses the config file, returning a dictionary.

    If the config is invalid or missing, this function
    calls sys.exit with an error value.
    """
    if not os.path.isfile(config_fp):
        log.error("File not found: %s" % config_fp)
        sys.exit(1)

    try:
        with open(config_fp) as ofile:
            config = json.load(ofile)
    except Exception as ex:
        log.error("Failed to read config: %s" % str(ex))
        sys.exit(1)

    # validate config file
    required_keys = [('pixiv_username', str), ('pixiv_password', str),
                     ('discord_hook_urls', list), ('main_tag', str),
                     ('sub_tags', list), ('wildcard', bool), ('allow_R18', bool),
                     ('allow_R18-G', bool), ('allow_manga', bool)]
    for key, val_type in required_keys:
        if not key in config:
            log.error("Config missing required parameter: %s" % key)
            sys.exit(1)
        if not isinstance(config[key], val_type):
            log.error("Config parameter %s must be %s" % (key, str(val_type)))
            sys.exit(1)

    # sub_tag should be a list of 3-tuples
    for tag in config['sub_tags']:
        if len(tag) != 3:
            log.error("Each sub-tag must be 3 items: tag, found string, missing string")
            sys.exit(1)
        for item in tag:
            if not isinstance(item, str):
                log.error("All subtag values must be strings: %s" % item)
                sys.exit(1)

    # discord_hook_urls should be a list of strings
    for url in config['discord_hook_urls']:
        if not isinstance(url, str):
            log.error("All Discord hook URLs should be strings: %s" % url)
            sys.exit(1)

    return config

def init_logging(level):
    """Initializes root logging facilities"""
    log.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(log_fmt))
    log.addHandler(handler)

def main():
    # parse args and initialize logging
    options, args = parse_args()
    init_logging(options.logging)
    # parse config
    config_fp = args[0]
    config = parse_config_or_die(config_fp)
    # some important file paths
    root_dir = os.path.dirname(os.path.realpath(__file__))
    history_fp = os.path.join(root_dir, 'history')

    # initialize Pixiv API
    try:
        api = pixiv.PixivAPI()
        api.login(config['pixiv_username'], config['pixiv_password'])
    except Exception as ex:
        log.error("Failed to initialize Pixiv API: %s" % str(ex))
        sys.exit(1)

    # load history
    history = load_history(history_fp)

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
