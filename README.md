# Kannada Dubbed Movies

A sourced list of films dubbed into Kannada, by original language. The site is plain
HTML built by `build_site.py` into `site/`; Cloudflare Pages publishes it.

## Files you edit

| File | What it's for |
|---|---|
| `press_dubs.csv` | Films confirmed by news reports (one row per film, with the source link) |
| `verification.csv` | Hand-checked decisions: `confirmed` (with a source), `unconfirmed`, or `exclude` |
| `site_config.json` | Site address and Formspree form ID |

Everything else is generated. After editing, run `python3 build_site.py` and push.

## Weekly update

`.github/workflows/update.yml` runs every Monday (or on demand from the Actions tab):

1. `update.py` checks Wikipedia articles edited since the last run and adds new matches
   to `kannada_dubs.csv`, then collects streaming-news headlines that mention Kannada.
2. `build_site.py` rebuilds the pages.
3. Changes are committed; Cloudflare publishes them.
4. If anything needs a human check, a GitHub issue lists it (you get an email).

## First-time setup

1. **GitHub:** create a repository, then in this folder run
   `git init && git add -A && git commit -m "First version" && git branch -M main`
   `git remote add origin https://github.com/YOUR-NAME/kannada-dubs.git && git push -u origin main`
2. **Cloudflare:** Workers & Pages → Create → Pages → Connect to Git → pick the repository.
   Framework preset: None. Build command: (leave empty). Build output directory: `site`.
   The project name you choose becomes the address, e.g. `kannada-dubs.pages.dev`.
3. **Site address:** if the address differs from `site_config.json`, change `site_url`,
   run `python3 build_site.py`, and push.
4. **Report form:** create a free form at formspree.io, put its ID (the part after `/f/`)
   in `site_config.json` as `formspree_id`, rebuild and push.
5. **Google:** add the site in Google Search Console and submit `/sitemap.xml`.
