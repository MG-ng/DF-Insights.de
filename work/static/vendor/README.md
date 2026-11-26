# Self-hosted third-party front-end files

These files are served from our own server instead of public CDNs, so a hijacked
or compromised CDN or npm package cannot change the JavaScript and CSS that
df-insights.de runs. Every file is an unmodified copy taken from the npm registry
tarball of the listed version (the same files jsDelivr and unpkg serve).

| Folder | Package | Version | File in package | Licence |
|---|---|---|---|---|
| `plotly/` | plotly.js-finance-dist-min | 4.3.0 | `plotly-finance.min.js` | MIT |
| `bootstrap/` | bootstrap | 5.0.2 | `dist/css/bootstrap.min.css` | MIT |
| `tom-select/` | tom-select | 2.4.3 | `dist/js/tom-select.complete.min.js`, `dist/css/tom-select.default.min.css` | Apache-2.0 |
| `toastify/` | toastify-js | 1.12.0 | `src/toastify.js`, `src/toastify.css` | MIT |
| `website-carbon-badges/` | website-carbon-badges | 1.1.3 | `b.min.js` | GPL-3.0-or-later |

The version is part of each file name, so a browser never keeps an old cached copy
after an update.

## SHA-256 checksums

```
b59dd6cf4bbfa20cd660d79aac9bf09ee1a779dd1cbaddb70899e5f155d71156  plotly/plotly-finance-4.3.0.min.js
7633b7c0c97d19e682feee8afa2738523fcb2a14544a550572caeecd2eefe66b  bootstrap/bootstrap-5.0.2.min.css
b797005cf23378fb38448b80dc57a33313a5c577b841765743bb1f289c4d53e6  tom-select/tom-select-2.4.3.complete.min.js
cb87fac73e4b0ae7b81ff75a8a5fe3452e8004a2479806ec164f78ddc39de66b  tom-select/tom-select-2.4.3.default.min.css
42dd6d2bfdd7153d1a702b2b45e468b7c85eec7426bb1e72938397d9a5db396e  toastify/toastify-1.12.0.js
dd168487b6e8ca4141ec79f407deace9c18ee7dcbd50a06f968fb009e3c89fec  toastify/toastify-1.12.0.css
93cb4279ebdd41fd5379a1506122b0abfabbbd98ca9be82410ed3d754231dcec  website-carbon-badges/website-carbon-badges-1.1.3.min.js
```

## Updating a file

```bash
npm pack tom-select@<version>          # npm checks the tarball's integrity hash
tar -xzf tom-select-<version>.tgz      # files are in package/
```

Copy the file in under a new versioned name, update the template that loads it,
the table and checksums above, and delete the old version.

Note: the carbon badge script still calls `api.websitecarbon.com` from the visitor's
browser to fetch the CO2 value. Self-hosting the script does not change that.
