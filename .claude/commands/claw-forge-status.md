# claw-forge status

Display a full project status card — zero-friction re-entry after leaving a session.

## What it shows

- **Project header**: name, spec file, model, and budget usage
- **Progress by phase**: progress bars, done/total counts, and phase health icons
- **Agent status**: current task, runtime
- **Next action**: the one thing you should do next (intervene, retry, start, etc.)

## Usage

```bash
claw-forge status
claw-forge status --config path/to/claw-forge.yaml
```

## Requirements

The state service must be running (`claw-forge state`) for live data. If offline, the command prints a warning and exits cleanly.
