# pdf-to-sheet

Upload Acrelec picking-list PDFs (`SalesOrd_SOUSACR*.pdf`) to a Google Drive folder. Every 5 minutes, a script attached to the Google Sheet reads them and fills in the next empty row of the **McDonalds** tab:

| A Store | C Address | D City | E Province | F Postal Code | J Must Ship Date | M Install Date |
| --- | --- | --- | --- | --- | --- | --- |
| 7228 | 900 Blvd Vachon N | Ste-Marie | QC | G6E 1M2 | 10/22/26 | 10/29/26 |

It runs entirely in Google, so your computer doesn't need to be on. It's free.

- **Only those columns are written.** Type, Product, Status, Staged by and the rest are left for you to fill in, and the formulas in column N aren't touched. The "next empty row" is the first row with nothing in column A.
- **Addresses are capitalized to match the hand-entered rows.** "900 blvd vachon n" becomes "900 Blvd Vachon N", and "424 RUE DE LA RIVIÈRE" becomes "424 Rue de la Rivière". Postal codes get a space (G6E 1M2). The street type is kept as the PDF writes it (Rd stays Rd, Road stays Road).
- **No duplicates.** A PDF is skipped if the sheet already has a row with the same store and ship date.
- **Afterwards**, each PDF moves to the folder's `Processed` subfolder, or to `Failed` if something couldn't be read. Either way, the file's Drive description says what happened (e.g. "added to row 523", or why it failed). To see it, right-click the file → **File information → Details**.

## Setup (one time, about 5 minutes)

1. **Make the upload folder.** In Google Drive, create a folder, e.g. `PDF Inbox`. Open it and copy the ID from the address bar: `drive.google.com/drive/folders/`**`this-part`**.
2. **Add the script to the sheet.**
   1. Open the Google Sheet and go to **Extensions → Apps Script**.
   2. Delete what's in the editor and paste in everything from [Code.gs](Code.gs).
   3. At the top, set `FOLDER_ID = '...'` to the ID from step 1. Save (⌘S).
   4. In the left sidebar, click **Services (+)**, choose **Drive API**, and click **Add**. The script needs it to read PDF text.
3. **Check it reads your PDFs correctly.** Upload one PDF to the folder. In the editor's function dropdown (next to **Run**), pick `testNewestPdf` and click **Run**.
   - The first time, Google asks for permission. Click **Review permissions**, choose your account, then **Advanced → Go to (project name) (unsafe) → Allow**. The "unsafe" warning appears for any script you write yourself.
   - The log at the bottom shows the text Google read from the PDF and the values it found. Nothing is written to the sheet.
4. **Turn it on.** Pick `setup` in the dropdown and click **Run**. It creates `Processed` and `Failed` in the folder and starts the 5-minute timer.

That's it. Upload PDFs to the folder, and within 5 minutes they show up in the sheet.

- **To stop it**, run `stop`.
- **To see what it's been doing**, go to **Executions** in the Apps Script sidebar. Each run lists the PDFs it handled.
- **To change which column gets what**, edit `COLUMNS` at the top of `Code.gs`. Values you can use: `store_number`, `street`, `city`, `province`, `postal_code`, `address` (all in one cell), `ship_date`, `install_date`, `sales_order`.

**How it reads PDFs:** Apps Script can't open a PDF directly. So Drive converts each PDF to a temporary Google Doc, the script reads its text, and then deletes the Doc. If a PDF ever lands in `Failed`, run `testNewestPdf` to see the text Google read from it.

## Mac version (optional)

`pdf_to_sheet.py` does the same thing from a folder on your Mac instead of Drive. It reads the PDF itself, then sends the row to the sheet through the same script. You only need this if you'd rather not use a Drive folder.

1. Install:
   ```sh
   cd pdf-to-sheet
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
2. In `Code.gs`, change `SECRET = 'CHANGE_ME'` to a word of your own. Then click **Deploy → New deployment → ⚙ → Web app**, with **Execute as: Me** and **Who has access: Anyone**. The script checks the secret instead of asking for a login. Copy the Web app URL (it ends in `/exec`). If you edit `Code.gs` later, redeploy with **Deploy → Manage deployments → ✏️ → Version: New version**, which keeps the same URL.
3. Copy `config.example.json` to `config.json`, then fill in `web_app_url` and `secret`, and set `inbox` to the folder to watch. The columns are already set up.
4. Run it:
   ```sh
   .venv/bin/python pdf_to_sheet.py                       # watch the inbox (Ctrl+C to stop)
   .venv/bin/python pdf_to_sheet.py --test samples/*.pdf  # print what would be read; sends nothing
   ```

`config.json`, `processed.json` and `samples/` are git-ignored, because the URL plus the secret is enough to add rows to the sheet.
