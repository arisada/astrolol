# Bugs

Here's a list of bugs observed and to be fixed

## Meridian flip timeouting

~~When the conditions are set to perform a meridian flip, clicking the button will put the mount in slewing mode. However the end of slew is not captured as should be when the flip fails. It ends up timeouting when the "slew_completed" message was sent long ago.~~

Fixed: `_wait_cond` now caps each condition-variable wait at 0.5s, so a missed `notify_all` wakeup is caught within half a second rather than after the full 120s `done_timeout`.


## Mount is parked message

~~the "mount is parked" message shows in the "park" box when the mount is still slewing in order to go in park position. It should wait until the mount is actually parked to show.~~ Fixed: `get_status()` now skips updating `is_parked` while `TELESCOPE_PARK` is BUSY.

## Messages from the Indi mount should be visible while in the mount menu

~~These messages are directly connected to what we were doing last in the menu. Don't just show the errors. Do the same as in the "Imaging" menu. Filter the messages so only the messages relevant to the mount (or imager in the imaging menu) are shown.~~ Fixed: mount page now has a filtered event log (mount + indi components). Imaging page also filtered to imager + indi.

