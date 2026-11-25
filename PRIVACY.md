# Privacy

Bookbench works on your computer. It has no account, no telemetry and no analytics, and it never sends
the text of your books anywhere. It only connects to the services below, and except for the update
check only when you ask for it.

| When | Where | What is sent |
|---|---|---|
| Update check (automatic at start, at most once a day by default; can be turned off under *Settings > General > Updates*) | GitHub (api.github.com) | A request for the list of releases. Nothing about you or your books. |
| *Look up* blurbs or covers | Google Books, Open Library | ISBN, title and author of the book. With your own Google Books key (*Settings > Online services*) the key too. |
| Blurbs from source profiles, dictionary entries from Claude (only with your own API key) | Anthropic (Claude API) | Title, author, series and language of the book and the instructions of the source profile; for the dictionary the term, its topic and the text of the wiki article. Claude may then fetch the pages named in the profile or search the web. |
| Building a dictionary from a wiki | The wiki you enter (MediaWiki) | Requests for the articles of that wiki. |
| Installing a missing package after an update, when you agree | Python Package Index (pypi.org) | The usual package download. |

Your settings, including API keys, are stored in plain text in the settings file on your computer
(`%APPDATA%\Bookbench` on Windows, `~/.config/bookbench` on Linux). They leave the computer only if you
export them yourself.

The services above have their own privacy policies:
[GitHub](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement),
[Google](https://policies.google.com/privacy),
[Open Library / Internet Archive](https://archive.org/about/terms.php),
[Anthropic](https://www.anthropic.com/legal/privacy),
[Python Package Index](https://policies.python.org/pypi.org/Privacy-Notice/).
