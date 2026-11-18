# Wingman Battle Buddy Review — QR site ready for Railway

This package contains the classroom peer review website, all original 14 rating items, two written comments, support for 4–25 students, unique student codes, automated submissions, an instructor-only results dashboard, and a QR generator. The site requires **hosting** before a personal phone can open it.

## Fast setup (browser-based, from a computer)

1. Create a new **private** repository at <https://github.com/new>. Unzip this download and upload the **files inside** the extracted folder to the root of that repository using **Add file → Upload files → Commit changes**. Do not upload any `data` folder, `.secret`, or real student data. GitHub repository is only the app code.
2. Sign in at <https://railway.com/>. Choose **New Project → Deploy from GitHub repo** and select your private Wingman repository. If prompted, authorize Railway to read that repository.
3. **Before collecting responses:** open your new service in Railway, select **+ Add Volume** / **New Volume** and attach it to your Wingman service. Set **mount path `/data`**. The server deliberately refuses to start without a mounted Railway volume: this prevents accidental loss of survey results after redeployment.
4. In the service **Variables** tab, add `WINGMAN_ADMIN_PASSWORD` with a **strong, unique password at least 16 characters** (20+ recommended). Do not put the password in GitHub. The instructor username is always `instructor`.
5. Open your service's **Settings → Networking → Public Networking → Generate Domain**. Railway will issue an HTTPS address like `https://your-app.up.railway.app`. The app reads `RAILWAY_PUBLIC_DOMAIN` automatically; you should not need to manually set the public URL.
6. **Deploy / Redeploy** the service after setting the volume, secret, and domain, if it is not already running. Open `https://your-app.up.railway.app/admin`. Enter username `instructor` and the password from step 4. If the site shows a failed deployment, review Railway's deployment logs.
7. In **Class setup**, paste 4–25 student names, select how many classmates each student evaluates, then click **Save class**. The app creates a QR image you can project on the classroom screen; it points to `/student`. Hand out the **individual student access codes** privately, ideally on paper, not on the projector.
8. Using a phone **not connected to your computer**, scan the QR using mobile data, pick a student name, enter its own access code, complete the assigned questions, and submit. Check **Instructor results** for the response. Use dummy student names for this test.

**Important:** When creating a new class, saving a roster change that alters names or review assignments deletes the current class's responses. **Export the reports before changing cohorts.** The app currently manages **one active class at a time**. Class-name-only edits preserve responses.

### What to expect

- Student URL: `https://your-app.up.railway.app/student` (shared QR)
- Instructor URL: `https://your-app.up.railway.app/admin` (password protected)
- Data: SQLite and session secret on Railway's persistent volume at `/data`
- Capacity: one concurrent application instance, sufficient for classroom-scale submissions; 4–25 reviewers
- Supported ratings: 1–5 plus N/O (Not Observed), omitted from numeric averages
- Student sign-in: individually assigned access codes, not identity-verifying CAC/SSO
- Results: average ratings, review counts, written feedback, exportable CSV. Keep raw reviewer-level data confidential.

### Minimum safeguards before using real names or peer comments

This is for **informal peer recognition**, not an authorized military records system. Even a local challenge-coin nomination can contain personally identifying and sensitive performance commentary. Check local procedures on students using personal phones and handling peer feedback. Keep the repository private, share the student QR only with the class, avoid unnecessary identifying details and allegations in free-text answers, use a unique admin password, keep student codes private, restrict CSV downloads, delete data once recognition is complete, and only collect what you need. This starter has no enterprise SSO, formal access logs, audit capability, advanced rate limiting, automatic archival, or institutional authorization. Student codes can be shared/impersonated. Require instructor review rather than allowing scores alone to decide awards.

### Hosting caveats

Railway has a free tier with usage limits; hosting can require a paid plan. You will be responsible for your own hosting account and any charges. Do not select a hosting option that will delete your data on restart (e.g. a free service with only ephemeral filesystem). Railway's attached **volume** is essential; the app blocks deployment if Railway detects no volume.

If the admin QR image encodes `configure-your-railway-domain.invalid`, your domain isn't yet set; generate a public Railway domain and redeploy, then refresh the admin page. **Never display the instructor-only access code roster to the class.**

### Manual local testing (synthetic data only)

Python 3.10+ recommended:

```bash
python -m pip install -r requirements.txt
# Mac/Linux
export WINGMAN_ADMIN_PASSWORD='your-own-unique-password-at-least-16-chars'
python server.py
```

On Windows PowerShell:

```powershell
$env:WINGMAN_ADMIN_PASSWORD='your-own-unique-password-at-least-16-chars'
python server.py
```

The local admin page is `http://127.0.0.1:8765/admin`. Local QR is **not** reachable on a separate phone; hosting is required.

Useful hosting references:
- <https://docs.railway.com/quick-start>
- <https://docs.railway.com/volumes/reference>
- <https://docs.railway.com/networking/public-networking>
- <https://docs.railway.com/pricing/plans>
