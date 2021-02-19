This bot is designed to poll character fanart from Pixiv and reupload it to
Discord.

## Setup

```
pip install -r requirments.txt
```

See `config-example.json` for an example config.

### Regarding Password Authentication

Pixiv has removed password authentication, breaking the intended workflow
for this program. As a temporary workaround, this bot now requires a
valid refresh token to be written to a file named `refresh`, placed at the
root of this repository.

The PixivPy developers are aware of this
[issue](https://github.com/upbit/pixivpy/issues/158) and have created a
semi-auto way of extracting valid refresh tokens. See
this [gist](https://gist.github.com/upbit/6edda27cb1644e94183291109b8a5fde)
for details.

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
