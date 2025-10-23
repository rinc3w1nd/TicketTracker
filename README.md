TicketTracker is a lightweight, local-first ticket and task-tracking system. It behaves like a help desk for one person or a small group, but without servers, user accounts, or admin rights. It runs entirely in user space on macOS or Linux using a simple Python stack (Flask, SQLAlchemy, SQLite, Jinja2).

Stack

It relies only on standard Python libraries and these components:
	•	Flask for the web interface
	•	SQLAlchemy + SQLite for the database
	•	Jinja2 for rendering pages
	•	Plain HTML/CSS for a responsive dark-mode UI
No daemon, cloud, or root privileges are required; it runs as a single user process.

⸻

Capabilities

1. Ticket management
Each task is a “ticket.” Tickets have a title, description, notes, requester, watchers, priority, due date, links, attachments, and tags. They can be searched, filtered, and sorted by due date, priority, or most recently updated.

2. Update log
Every ticket carries a chronological stream of updates — written notes with optional attachments and links. This acts as a permanent audit trail. Status changes automatically create an update entry, so history is always complete.

3. Status workflow
Tickets move through clear states:
	•	Open → In Progress → On Hold → Resolved → Closed or Cancelled
	•	On Hold includes a reason, drawn from presets or a custom entry.
	•	Cancelled and Closed are terminal; cancelled items display with a strike-through.
Color indicates urgency, not state, except for the On Hold and Resolved overrides.

4. SLA-based coloring
Each ticket’s color represents its time sensitivity:
	•	Blue to red gradient shows how close or past due a ticket is.
	•	When no due date exists, color follows how long it’s been open relative to its priority.
	•	On Hold turns lavender; Resolved turns pale green.
All colors are configurable in a JSON file so the user can change palettes or thresholds.

5. Tagging and filtering
Tags organize work across projects or themes. Multiple tags can be applied and filtered with either OR or AND logic. Tags also appear as small chips in the UI for quick scanning.

6. Attachments and links
Both tickets and individual updates can hold uploaded files and reference links. Attachments stay local and can be downloaded from within the interface.

7. Configuration and customization
Everything—the colors, SLA thresholds, hold reasons, and priorities—is stored in a simple JSON file. No code edits or database migrations are needed. The user can modify look and timing, then restart the app.

8. Search and sort
A unified search box matches text across titles, descriptions, notes, requesters, watchers, and tags. Sorting and filtering keep the ticket list usable even for large backlogs.

9. Safety and self-containment
All data lives in a single SQLite file and local upload directory. Nothing leaves the host. The app works entirely offline and can be backed up by copying one folder.

⸻

Requirements and Expected Behavior
	•	Runs locally in any user directory, no admin rights required.
	•	Opens in a browser and serves a small dashboard on localhost.
	•	Provides a smooth ticketing experience: add, update, close, filter.
	•	Visually signals urgency through color, state through icons or labels.
	•	Remains consistent and recoverable: nothing transient, no hidden state.
	•	Flexible enough to act as personal help desk, client tracker, or to-do manager.

In short: TicketTracker should function as a small, private help-desk system that visually prioritizes tasks by time and importance, maintains full history and attachments, and stays entirely under the user’s control.
---

## Getting started

### Prerequisites
- Python 3.10 or newer
- `pip` for installing Python packages

### Installation
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration
Runtime behaviour is driven by `config.json` in the project root. The file controls:
- database location (`database.uri`, defaults to SQLite beside the project)
- uploads directory (`uploads.directory`)
- workflow statuses, priorities, and hold reasons
- SLA timing thresholds used for ticket colouring
- palette overrides for statuses, priorities, and tag chips
- Flask session secret (`secret_key`). For production deployments set the `TICKETTRACKER_SECRET_KEY` environment variable to override the value stored in the JSON file.

SLA configuration now works in stages. For due dates, the `sla.due_stage_days` list expresses the day thresholds (defaults: 28/21/14/7) that map to the gradient stages. Tickets transition from stage 0 when they are far from the due date through stages 1–3 as they approach it, and finally to the `overdue` colour once the due date passes. Backlog items without due dates use `sla.priority_stage_days`, where each priority has an array of ascending day limits; once a ticket ages beyond the final value it is treated as overdue.

The gradient palette exposes five keys—`stage0`, `stage1`, `stage2`, `stage3`, and `overdue`. By default the colours flow from a light blue baseline through yellow and orange to red and finally crimson for overdue tickets. Custom configurations may omit individual entries; any missing colours fall back to the defaults above.

You can provide a different configuration by setting `TICKETTRACKER_CONFIG` to an alternate JSON file path before starting the app.

Clipboard exports are driven by the `clipboard_summary` section. Both `html_sections` and `text_sections` accept ordered lists of section names, allowing you to reorder or omit parts of the ticket summary. Available sections include:

- `header` – Renders the ticket title as the clipboard heading.
- `timestamps` – Shows when the ticket was created and last updated.
- `meta` – Lists status, priority, due date, and SLA countdown details.
- `people` – Summarises the requester and watchers.
- `description` – Outputs the ticket description field.
- `links` – Copies reference links supplied on the ticket.
- `notes` – Copies the internal notes field.
- `tags` – Lists tag names associated with the ticket.
- `updates` – Includes the most recent ticket updates up to the configured limit.

The `updates_limit` value controls how many timeline entries are included when the `updates` section is enabled. Leaving `text_sections` empty instructs the app to reuse the HTML section list for the plain-text export. Removing the `timestamps` section omits created/updated lines from the summaries.

### Running the development server
```bash
flask --app tickettracker.app:create_app run --debug
```

The command creates the SQLite database (if missing), ensures the uploads directory exists, and serves the UI at <http://127.0.0.1:5000>.

Uploaded attachments are stored locally under the directory defined in the JSON configuration (defaults to `uploads/`). Backing up the database file and uploads folder is sufficient to preserve all data.

### Demo mode and sample data

TicketTracker ships with a comprehensive demo dataset (`tickettracker/demo_data/demo_tickets.json`) that exercises overdue, on-hold, resolved, and backlog scenarios with associated updates, tags, and attachments. Operators can enable demo mode from the **Settings → Demo mode controls** panel or via the CLI:

```bash
python -m tickettracker.cli demo enable        # load demo data and snapshot live state
python -m tickettracker.cli demo refresh      # discard demo changes and reload the dataset
python -m tickettracker.cli demo disable      # restore the original database and uploads
```

Enabling demo mode snapshots the current SQLite database and uploads directory inside the application instance path, replaces them with the curated demo dataset, and ensures all temporary changes are discarded when demo mode is disabled. The settings UI surfaces enable/disable/refresh buttons and shows when the dataset was last loaded so you can safely demonstrate features without risking production data.

### Workflow highlights
- Tickets can be created, edited, filtered, and searched from the dashboard.
- Status transitions automatically create audit-log entries on the ticket timeline.
- Attachments may be added when creating tickets or posting updates, and can be downloaded from the detail page.
- SLA-based colouring, tag chips, and hold-reason presets all respond to configuration changes without code edits.

## License

TicketTracker is distributed under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software, provided that the copyright notice and permission notice are included in all copies or substantial portions of the software.

### Support Development

If TicketTracker makes your day-to-day work easier and you’d like to say thanks, you can optionally send a tip using any of the wallets below. Every contribution goes right back into the coffee and gadgets fund.

<img src="static/img/Bitcoin.svg" alt="Bitcoin logo" height="24"> **Bitcoin** - `bc1qnj60jqgp5uwu8uek843jxqlg7s5a05vlvatsw7`
<img src="static/img/Ethereum.svg" alt="Ethereum logo" height="24"> **Ethereum** - `0x4c12c4439D10962c5d2d9B04CFA3246b2A399d58`
<img src="static/img/Litecoin.svg" alt="Litecoin logo" height="24"> **Litecoin** - `ltc1q4metd98pvz6v0y4akr33rcq3pyana7sr97gjuu`
<img src="static/img/Dogecoin.svg" alt="Dogecoin logo" height="24"> **Dogecoin** - `D6iYuzD6moPusdciMBQRfyryxNJsmiVtRH`
<img src="static/img/Shiba-Inu.svg" alt="Shiba Inu logo" height="24"> **Shiba Inu** - `0x4c12c4439D10962c5d2d9B04CFA3246b2A399d58`
<img src="static/img/xrp.svg" alt="XRP logo" height="24"> **XRP** - `rhB3NffCBbrAVkdAVFsVQWHa3NBJLKXaf1`
<img src="static/img/Monero.svg" alt="Monero logo" height="24"> **Monero** - `4BAMFNn71DhZTd2G6kmESPG7n3sG9pW4bWsKAZaKjZ67EMnTuJqJW1DH1cr1scZxP57BQshpEr2fz5KKSP4K3ScvRkH7N8S`

> Tips are always appreciated but never expected—they don’t grant special access, support guarantees, or priority handling.
