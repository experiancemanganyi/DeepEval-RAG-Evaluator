# Users, bulk review and cleanup

## Start the updated version
Keep Visual Studio open if you wish. In the terminal running E.V.O, press Ctrl+C, then run `./Start-EVO.ps1` from the project folder. Open http://127.0.0.1:8080 and refresh. Sign in with your name and surname.

## Add, view, edit and remove users
1. Open **Users** in the sidebar. It reads the users already saved in the local database.
2. Click **Add user**, enter name and surname, and save. New names entered at sign-in are also saved automatically.
3. Click **Edit** beside a user to update the name or surname. The existing user ID and activity history are preserved.
4. Click **Remove** and confirm to remove an unwanted profile from the active list and revoke its sessions. You cannot remove your own current profile; sign in as another user first.
5. Expand **Removed users** and click **Restore** if needed. Removed identities cannot sign in or be added again as duplicate profiles.

Names are checked against the database without case or extra-space differences: `Jane Doe` and ` jane DOE ` reuse the same identity. Two people with identical names cannot have distinct identities in this name-only system. Name-only sign-in is self-declared, without passwords or roles. All users share the workspace.

The header shows the first initial and surname. Open **Settings → User activity** to see who changed records. No direct SQL editing is needed. The default database is `data/evo.sqlite3` in the project folder; `EVO_DB_PATH` can override it. API keys are not written to the activity log.

## Review question references in bulk
1. Open **Reference library** and select your application.
2. Tick individual unapproved questions, or click **Select all unapproved**.
3. Click **Generate proposals for selected**. One background job processes the selection automatically; you do not need to open each question. An OpenAI key in Settings is required for generation.
4. When proposals appear, click **Approve & save selected**. Review all displayed content, tick **I reviewed this content and approve it for evaluation**, and save.

If selected references are missing content, clicking approval starts proposal generation first; review and approve after it finishes. Generated text is never silently approved. Individual **Review** and **Generate proposal** remain available.

Only the latest active reference per question is shown by default. Use **Approved only** to see verified references. Approval does not duplicate the question. Older reference versions remain behind **Show history** so previous test results retain their original evidence.

## Review test cases in bulk
1. Open **Datasets**, select the application, then **Review cases** beside the dataset.
2. Tick cases individually or use **Select all unapproved**.
3. Click **Generate proposals for selected** to propose expected feedback for every saved candidate answer. Approve the question references first. Candidate answers and case IDs are preserved.
4. When the job finishes, the cases refresh automatically. Click **Approve & save selected**, review the displayed content, tick the review statement, and save.

If expectations are missing, approval starts generation first. Individual **Review** still lets you edit and save a case or click **Generate proposal**. Save any edits before generating. Partial generation failures preserve successful proposals; failed items can be retried. Concurrent edits are not overwritten. Previously captured run snapshots remain unchanged.

Proposals help prepare reference data; evaluation of connected tools still uses the configured DeepEval metrics. Generating or approving proposals does not run the connected application or upload a test report by itself.

## Remove unwanted items
- **Test runs → Remove run**: available for completed, completed-with-errors, and cancelled runs. Wait for the worker to stop before removing.
- **Datasets → Delete**: removes a dataset from the working list. Finish or cancel active runs using it first.
- **Applications → Remove**: removes the local connection. Finish or cancel its pending and active runs first. This does not modify the connected application's server.

Removal hides items from working lists while retaining database history, audit records and existing result snapshots. It does not delete reports already uploaded to Confident AI. Reconnecting an application with the exact same name reuses its existing local application record.

These changes affect the local E.V.O project only. The AI Interview server code was not changed.


## Uploaded documents and process cards
- In **RAG testing → Documents**, click **Remove** beside an unused document and confirm. It disappears from the document list and document reference library. Documents currently used for golden generation cannot be removed until the job finishes.
- Removal deactivates local chunks and preserves saved evaluation snapshots. Existing Supabase copies are not deleted. Uploading the same document again makes its chunks available again without duplicating identical chunks.
- At the bottom of a page, use **Remove** on a completed or failed process card, or **Clear completed & failed processes** to dismiss all finished cards. This does not delete the datasets/results produced by those jobs. Queued, running and sign-in processes cannot be dismissed this way.
- Removed applications are excluded from every **Overview** count, score, chart, technology breakdown and recent-run entry. Historical records remain available outside Overview.

Restart E.V.O with `./Start-EVO.ps1` and refresh your browser to load these controls and the database migration. Run `./Publish-EVO.ps1` again when ready to publish these additional changes; the earlier successful push did not contain them.
