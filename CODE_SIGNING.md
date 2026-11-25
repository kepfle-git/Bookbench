# Code signing policy

Status: Bookbench has applied to the SignPath Foundation open-source program. Until it is accepted, the
Windows downloads are not signed (Windows SmartScreen: *More info* > *Run anyway*).

Once accepted: **Free code signing provided by [SignPath.io](https://signpath.io), certificate by
[SignPath Foundation](https://signpath.org).**

## What is signed

- `Bookbench.exe`, the program started by the Windows setup
- `Bookbench_Setup_<version>.exe`, the Windows installer

Only these files, built from this repository, are signed with the project's certificate. Third-party
components shipped with them (Python, Qt for Python and other libraries, see
[THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt)) keep their own signatures or are unsigned; they are
not represented as Bookbench's own code. Linux has no binaries; `install.sh` installs the source code.

## How releases are built

- Every Windows release is built by GitHub Actions from a tag in this public repository
  ([workflow](.github/workflows/windows-setup.yml)), with PyInstaller and Inno Setup.
- Nothing built on a personal computer is submitted for signing.
- Each signing request is approved by hand by the approver below, after checking that it belongs to a
  tagged release.
- The release page lists SHA-256 checksums of the setup (`SHA256SUMS`).

## Team

| Role | Members |
|---|---|
| Author (commits without further review) | [Sebastian Kopf (kepfle-git)](https://github.com/kepfle-git) |
| Reviewer (reviews contributions from others, e.g. pull requests) | [Sebastian Kopf (kepfle-git)](https://github.com/kepfle-git) |
| Approver (approves each signing request) | [Sebastian Kopf (kepfle-git)](https://github.com/kepfle-git) |

All members use multi-factor authentication for GitHub and SignPath.

## Privacy

Bookbench does not transfer any information to other networked systems unless you ask for it, apart
from the update check, which can be turned off. Details: [PRIVACY.md](PRIVACY.md).
