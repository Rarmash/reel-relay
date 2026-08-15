# iOS Shortcut setup

Create one Shortcut per person, because anyone who can inspect or copy a Shortcut can also see its revocable user token.

1. In Shortcuts, create a new shortcut named **Save Instagram Reel**.
2. Open its details, enable **Show in Share Sheet**, and limit accepted input to **URLs**.
3. Add **Get URLs from Shortcut Input**, then **Get Item from List** (First Item).
4. Add **Get Contents of URL** and configure it as follows:
   - URL: `https://reels.rarmash.ru/api/v1/download`
   - Method: `POST`
   - Headers: `Authorization` = `Bearer YOUR_USER_TOKEN`
   - Request Body: JSON
   - JSON field `url`: the URL produced by the previous action.
5. Add an **If** action that checks whether the result has the media type `video/mp4`. If it does, use **Save to Photo Album** and then **Show Notification** with “Reel saved”.
6. In the Otherwise branch, get text from the response and show “Could not download this Reel”. Do not pass the error response to **Save to Photo Album**.

Exact action labels vary slightly by iOS version. Test with a public Reel before sharing the Shortcut. Give every friend a separately created token; never embed the admin token. If a shared Shortcut leaks, revoke only that user's token and issue a replacement.
