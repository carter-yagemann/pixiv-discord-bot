This bot is designed to poll character fanart from Pixiv and reupload it to
Discord.

## Setup

```
pip install -r requirments.txt
```

See `config-example.json` for an example config.

## Usage

```
./bot.py [options] <config_file>
```

This is a polling-based system, so you'll probably want to use `cron` or
something similar to automatically run the script periodically.

## Configuration

Each config file contains a
"main tag" that is intended to be a series (e.g., game, TV show) and a
list of "sub-tags" (e.g., characters). Picked images must be tagged with
both the main tag and one or more sub-tags. If you want to grab images
based on only one tag, you can have an empty sub-tags list and set
`wildcard` to true.

`wildcard` controls whether the bot will additionally pick one image based
solely on the main tag, without considering the sub-tags.

You can filter what kind of images are picked using `allow_R18`, `allow_R18-G`,
and `allow_manga`. If you don't know what any of these terms mean, you probably want
to set allow to `false`.

You can create a Discord hook URL by going to a channel's settings and clicking
`Integrations->Webhooks->Create Webhook`.
