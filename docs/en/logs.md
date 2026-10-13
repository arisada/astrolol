# Logs

The **Event Log** lists what astrolol did and what went wrong, live: devices
connecting, exposures, slews, guiding, plate solves, autofocus runs, errors.

## Filtering

The pills at the top filter the list:

- **All** shows everything.
- One pill per component (INDI, device, mount, imager, focuser, and the enabled plugins that
  have their own) shows only that component. Select several to see them together.
- **Errors** shows the errors.

The counter on the right shows how many events match out of how many are kept.

Only the most recent events are kept in memory. The complete history is in the file
`astrolol.log` on the telescope computer; include it when you report a problem.

## Verbosity

The gear opens **Log verbosity**: one switch per component. Turn a component to **debug** to
see its detailed messages while you investigate a problem. These switches **reset on
restart**, so you cannot forget one on.

To see the raw conversation with INDI drivers, use *INDI protocol logging* in
[Options](options.md#indi-server).
