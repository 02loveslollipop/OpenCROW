# Wiki publication policy

`docs/wiki-manifest.json` is the public page allowlist and ordering source. `scripts/generate_wiki.py` generates `Home.md`, `_Sidebar.md`, `_Footer.md`, selected pages, and redirect stubs with stable version/tag/SHA metadata.

Generated Wiki pages are immutable between stable releases. Direct Wiki edits are unsupported and overwritten by the next successful stable publication. Never put private operations, unpublished secrets, credentials, or incident data in a manifest-selected source.

Publication targets `02loveslollipop/OpenCROW.wiki.git` with a dedicated deployment credential. Replace pages in a temporary clone and push only after the full generated tree validates.
