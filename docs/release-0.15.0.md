# v0.15.0 — Useful Actions and Artifacts

This release turns approved suggestions into useful local actions while keeping the user in control.

## Highlights

- Calendar suggestions show conflicts first and create a local calendar record only after explicit approval. Calendar write-back to external services remains disabled.
- Email follow-up drafts are editable and stored locally. This release never sends mail.
- Four reusable goal templates cover health follow-up, exam study, travel preparation, and bills or subscriptions.
- Versioned Artifacts support plans, checklists, timelines, and budget boards, with safe preview, export, edit-conflict protection, and source metadata.
- Web and Android clients expose the new calendar, draft, template, and Artifact workflows.
- Database schema 18 adds ordered, rollback-safe migrations for the new records.

## Safety boundaries

- No calendar event or email is written to an external provider.
- Local calendar creation requires a short-lived approval and is idempotent.
- Deleting an Artifact does not delete its source chat, goal, or memory.
- File previews escape active content and block network, script, image, and frame loading.

## Validation

- Full Python regression suite.
- Android unit tests and debug APK build.
- macOS frozen-app smoke test and Windows installer workflow.
- Branch separation checks for `main`, `win`, and `android`.
