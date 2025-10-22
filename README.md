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