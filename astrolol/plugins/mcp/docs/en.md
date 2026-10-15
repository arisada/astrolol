# AI assistants

*Plugin: AI assistants.* Lets Claude and other AI assistants look at your rig and operate it. You
can ask in plain words: "what is the mount doing?", "centre on M31 and take a 30 s test frame",
"focus, start guiding and run tonight's list". The assistant calls astrolol's tools, shows you
what it found, and reports back.

An assistant can do exactly what the sign-in it uses can do (see [Security](../../security/docs/en.md)):

| Access level | What the assistant can do |
|---|---|
| Viewer | Look: status, images, events. Nothing moves. |
| Operator | Operate: slew, park, expose, focus, guide, run the sequencer. |

When security is off, the assistant has full operator access, like anyone on your network. Turn
security on and give the assistant its own **viewer** token to let it look without touching anything.

## Connecting

Open this page: it shows the address to give your assistant and, for Claude Code, a command to
copy. It looks like this:

```
claude mcp add --transport http astrolol http://astrolol.local:8000/plugins/mcp
```

With security on, add the access token (created on the Security page, **API tokens**):

```
claude mcp add --transport http astrolol http://astrolol.local:8000/plugins/mcp \
  --header "Authorization: Bearer <token>"
```

Other assistants that support remote MCP servers take the same address, and the same header if
they let you set one. The computer running the assistant must be able to reach astrolol; no
program has to be installed on it.

## The skill

**Download SKILL.md** gives you a short guide for Claude: the order of a night, the units
(coordinates in degrees, status in hours), and the safety habits (stop guiding before slewing,
park at the end, ask before starting a long run). Save it as `SKILL.md` in a folder named
`astrolol-observing` inside your skills folder (for example `~/.claude/skills/`). The assistant
works without it but makes fewer mistakes with it.

## What it can do

The list at the bottom of the page shows every tool and whether it only reads. In short:

- **Look:** an overview of all devices, mount position, camera and focuser status, recent events, any page of the API read-only.
- **Point:** search an object, check when it is visible, slew, centre by plate solving, park.
- **Image:** take an exposure and see a preview, cool the camera, change filter.
- **Focus and guide:** autofocus, start/stop guiding, dither.
- **Run a night:** build the sequencer queue, check it, start, pause, stop.
- **Stop everything:** one call halts the mount, camera, focuser, guiding and sequencer.

Tools for a feature appear only when that feature's plugin is on. Slews, parking and autofocus wait
until they finish, so the assistant does not have to keep asking.

## Good to know

- Enabling or disabling the plugin takes effect after a restart.
- The assistant sees images as small previews, enough to judge focus, trails and exposure. The full data stays on the astrolol machine.
- Look at **Logs** (verbosity: AI assistants) if a tool call fails.
