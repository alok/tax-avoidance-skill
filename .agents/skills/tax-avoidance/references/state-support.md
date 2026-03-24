# State Support

This project should capture state information early, even when the actual state return is not yet automated.

## Design Goal

Separate **state intake** from **state calculation**:

- intake happens now
- calculation ships state by state later

That lets users gather the hard-to-recreate facts once, while the repo grows into actual state support.

## Input Shape

Use a top-level `state` object in the flow input:

```json
{
  "state": {
    "resident_state": "CA",
    "work_states": ["CA", "NY"]
  }
}
```

## Current Behavior

- render resident state and work states in the dossier
- attach state follow-up notes to `missing-items.md`
- show module status for known states
- preserve multistate information instead of throwing it away

## Initial Module Targets

- `CA`: resident and nonresident forms exist and are linked to official FTB sources
- `NY`: resident and nonresident forms exist and are linked to official DTF sources

These are **planned**, not automated.

## Why This Matters

TurboTax premium products win by not losing state context once the user enters it. This repo should do the same:

- keep resident state
- keep work-state list
- keep state withholding and source-income details when available
- avoid forcing the user to restate that context later
