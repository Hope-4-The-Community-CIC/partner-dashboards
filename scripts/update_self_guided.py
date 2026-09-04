name: Update self-guided dashboard

on:
  repository_dispatch:
    types: [update-self-guided]

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest

    env:
      DASHBOARD_KEY: ${{ github.event.client_payload.dashboard_key }}
      LATEST_DATE: ${{ github.event.client_payload.latest_date }}
      WEEKLY_UPTAKE: ${{ github.event.client_payload.weekly_uptake }}
      ENROLLED_TOTAL: ${{ github.event.client_payload.enrolled_total }}
      QUOTA: ${{ github.event.client_payload.quota }}

    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Configure Git
        run: |
          git config user.name "hope-dashboard-bot"
          git config user.email "actions@users.noreply.github.com"

      - name: Update and push dashboard safely
        run: |
          for attempt in 1 2 3 4 5
          do
            echo "Attempt $attempt for source: $DASHBOARD_KEY"

            git fetch origin main
            git reset --hard origin/main

            python scripts/update_self_guided.py

            git add -- '*/data.json'

            if git diff --cached --quiet; then
              echo "No changes required. Dashboard is already up to date."
              exit 0
            fi

            git commit -m "Update self-guided dashboard: $DASHBOARD_KEY"

            if git push origin HEAD:main; then
              echo "Dashboard update pushed successfully."
              exit 0
            fi

            echo "Another dashboard changed main first. Retrying from the latest version..."
            sleep 3
          done

          echo "Could not push dashboard update after 5 attempts."
          exit 1
