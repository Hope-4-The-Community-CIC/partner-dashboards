# Hope partner dashboards

This repository can host several public partner dashboards from one GitHub Pages site.

## Structure

- `/partner-one/` — first live dashboard
- `/partner-template/` — copy this folder when adding another funder/partner

Each partner folder has:
- `config.json` — partner name, programme name, logo and Qualtrics public quota dashboard URL
- `data.json` — self-guided current count, quota and optional weekly history
- `index.html` — dashboard design

## First dashboard

The first dashboard is already wired to:

`https://coventryhls.fra1.qualtrics.com/public-quotas?SID=SV_cvy7ROwKy6NBcfI`

The page tries to show that Qualtrics public dashboard live inside the H4C partner page. If Qualtrics prevents iframe embedding, the dashboard still provides a direct public link. In that case, the next step is to use Qualtrics' public CSV quota export instead.

## What is needed from the weekly self-guided sheet

Minimum fields:
- reporting/update date
- current enrolled participants
- quota/target

Optional for a weekly trend:
- participants enrolled since last check

Your existing sheet already stores `Updated on`, `Enrolled Participants`, and `Participants enrolled since last check`, so no new detailed reporting table is needed.

For a first manual version, update `partner-one/data.json` once a week.

Example:
```json
{
  "updatedAt": "2026-08-07",
  "selfGuided": [
    {
      "name": "Self-guided Hope Programme",
      "count": 268,
      "target": 5000
    }
  ]
}
```

## Adding another funder

1. Copy `partner-template`.
2. Rename the copy, for example `macmillan` or `pmos`.
3. Change that folder's `config.json`.
4. Replace the partner logo.
5. Change the self-guided count and quota in `data.json`.

Each folder gets its own public address on GitHub Pages.

## Data protection

Only aggregate counts, dates, quotas, programme names and logos should be stored here.
Do not upload participant names, email addresses, postcodes, response-level Qualtrics exports, API keys, tokens or database credentials.
