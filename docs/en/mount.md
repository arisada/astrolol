# Mount

The Mount page shows where the mount points and lets you move it. With no mount connected it
says *No mount connected*: connect one in [Equipment](equipment.md) or activate a
[profile](profiles.md).

![Mount](../images/mount.png)

## Position

The current pointing:

| | |
|---|---|
| RA / Dec | Equatorial coordinates. Switch between **JNow** (of date, as the mount sees the sky) and **J2000** (as catalogues give them). |
| Alt / Az | Altitude above the horizon and azimuth. |
| HA | Hour angle; how far the mount is from the meridian. |
| LST | Local sidereal time. |
| Pier | Which side of the pier the telescope is on (East / West), and how long until (or since) the meridian. |

Two sky maps show the mount's position: one centred on the **celestial pole** (equatorial
view) and one centred on the **zenith** (horizontal view, what you see standing under the sky).

The location and time come from the site in the active profile, so check the site if the
altitude or hour angle look wrong.

## Target

The fields follow the mount's position until you change them. Type coordinates (RA in hours,
minutes, seconds; Dec in degrees, minutes, seconds, with N/S) or use the arrows above and below
each field. Coordinates are entered in **J2000** by default; switch to **JNow** if yours are of
date. Once you have edited them, **↺ live** makes the fields follow the mount again.

- **Set Target** records the target without moving (it names the frames and is used by other
  pages).
- **Slew** moves the mount there.
- **Sync** tells the mount it is pointing at these coordinates, which corrects its pointing.
  Use it only when you know where the telescope really points; [Plate Solving](platesolve.md)
  does it for you.
- **Stop** aborts a slew.

The easiest way to set a target is from the [Target](target.md) page.

## Tracking

The switch turns tracking on or off. The list selects the rate: **Sidereal** (stars),
**Lunar** or **Solar** (the last two only if the mount's firmware supports them). Tracking
cannot be turned on while the mount is parked.

## Park

- **Park** sends the mount to its park position and stops tracking; **Unpark** releases it.
- **Set as park position** makes the current position the park position.
- **Park automatically at** a local time, for example 06:00, so the mount is safe at dawn even
  if you are asleep.

## Meridian & horizon

- **Meridian Flip** turns the mount over to the other side of the pier. The button explains
  when a flip is not possible: the meridian has not been crossed yet, the pier side is already
  right, or the mount is more than 2 h past the meridian (slew to the target instead).
- **Flip automatically when HA >** a number of hours past the meridian.
- **Meridian limit**: how far the RA axis may turn past the meridian, either way. Past it,
  tracking stops and slews are refused. Enforced by mounts that support it (the
  [EQMOD](eqmod.md) driver); INDI drivers keep their own limits.
- **Horizon limit**: a flat horizon in degrees of altitude. GoTos below it are refused. When a
  tracking mount sinks below it, astrolol does once what you chose: **stop tracking**, **park**
  or **do nothing**.

If you image with the [Sequencer](sequencer.md), let it handle flips: it flips between frames
instead of in the middle of one.

## Nudge

Arrow buttons move the mount **North**, **South**, **East** and **West**. Hold to move, release
to stop. **Rate**: *Guide* (very slow), *Center*, *Find* or *Max*.

## Device properties

The gear next to the mount name opens the driver's full list of settings. See
[Device properties](interface.md#device-properties).
