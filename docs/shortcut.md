# iOS Shortcut setup

Create one Shortcut per person, because anyone who can inspect or copy a Shortcut can also see its revocable user token.

The asynchronous jobs API avoids the request timeout on long Reels. The first request only starts the job; short polling requests wait for it to become ready.

1. In Shortcuts, create a new shortcut named **Save Instagram Reel**.
2. Open its details, enable **Show in Share Sheet**, and limit accepted input to **URLs**.
3. Add **Get URLs from Shortcut Input**, then **Get Item from List** (First Item).
4. Add **Get Contents of URL**:
   - URL: `https://reels.rarmash.ru/api/v1/jobs`
   - Method: `POST`
   - Headers: `Authorization` = `Bearer YOUR_USER_TOKEN`
   - Request Body: JSON
   - JSON field `url`: the URL produced by the previous action.
5. Get dictionary value `id` from the response and save it in a variable named `Job ID`.
6. Add a **Repeat** action for 120 iterations. Inside it:
   - Wait 2 seconds.
   - Get Contents of `https://reels.rarmash.ru/api/v1/jobs/Job ID`, substituting the `Job ID` variable at the end. Use method GET and the same Authorization header.
   - Get dictionary value `status`.
   - If it equals `ready`, get contents of `https://reels.rarmash.ru/api/v1/jobs/Job ID/download` with method GET and the same header. Set the returned file name to `reel.mp4`, save it to the desired photo album, show “Reel saved”, then add **Stop This Shortcut**.
   - If it equals `failed`, get dictionary value `message`, show it, then add **Stop This Shortcut**.
7. After the Repeat block, show “The Reel is still being processed. Try again later.”

The loop allows up to four minutes, while every individual HTTP request remains short. A ready file is retained on the server for ten minutes by default and deleted immediately after download. Exact action labels vary slightly by iOS version. Test with a public Reel before sharing the Shortcut. Never embed the admin token.
