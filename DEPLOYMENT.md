# Deploying Optibreed to Render.com

## Prerequisites

- A GitHub, GitLab, or Bitbucket account
- A Render.com account (free tier available)
- Your Optibreed code in a Git repository

## Deployment Steps

### 1. Prepare Your Repository

Make sure your repository includes these files (already configured):

- `Dockerfile` - Container configuration
- `render.yaml` - Render.com service configuration
- `requirements.txt` - Python dependencies
- `.gitignore` - Files to exclude from Git

**Important:** Don't commit `.env` file to Git - it contains secrets!

### 2. Push to Git Repository

```bash
# Initialize git if not already done
git init

# Add all files
git add .

# Commit
git commit -m "Prepare for Render.com deployment"

# Add remote (replace with your repository URL)
git remote add origin https://github.com/yourusername/optibreed.git

# Push to repository
git push -u origin main
```

### 3. Deploy on Render.com

#### Option A: Using render.yaml (Recommended)

1. Go to [https://render.com](https://render.com) and sign in
2. Click **"New +"** → **"Blueprint"**
3. Connect your Git repository
4. Render will automatically detect `render.yaml`
5. Click **"Apply"**
6. Your app will be deployed automatically!

#### Option B: Manual Setup

1. Go to [https://render.com](https://render.com) and sign in
2. Click **"New +"** → **"Web Service"**
3. Connect your Git repository
4. Fill in the details:
   - **Name:** `optibreed` (or your preferred name)
   - **Environment:** Docker
   - **Plan:** Free (or choose paid plan)
   - **Branch:** main (or your default branch)
5. Click **"Create Web Service"**

### 4. Configure Environment Variables

After deployment is created:

1. Go to your service dashboard on Render
2. Click **"Environment"** in the left sidebar
3. Add environment variable:
   - **Key:** `SECRET_KEY`
   - **Value:** Generate a random secret (e.g., use Python: `python -c "import secrets; print(secrets.token_hex(32))"`)
4. Click **"Save Changes"**

The service will automatically redeploy with the new environment variables.

### 5. Access Your Application

Once deployed, Render will provide you with a URL like:

```
https://optibreed.onrender.com
```

Your application will be live at this URL!

## Important Notes

### Free Tier Limitations

- Apps on the free tier spin down after 15 minutes of inactivity
- First request after inactivity will take 30-60 seconds to wake up
- 750 hours/month usage limit (shared across all free services)

### Upgrade to Paid Plan

For production use, consider upgrading to a paid plan:

- **Starter ($7/month):** No spin-down, faster response times
- **Standard ($25/month):** More resources, better performance

### Session Storage Warning

⚠️ **Important:** The current app uses in-memory session storage (`app.sessions = {}`). This means:

- Sessions are lost when the app restarts or spins down
- Users will lose their data if the app redeploys

**For production, consider using:**

- Redis for session storage
- Amazon S3 or Cloud Storage for file uploads
- PostgreSQL/MongoDB for data persistence

### Monitoring

- Check logs: Render Dashboard → Your Service → Logs
- Monitor performance: Render Dashboard → Your Service → Metrics
- Set up alerts: Render Dashboard → Your Service → Settings → Notifications

## Updating Your Application

When you push new code to your repository:

```bash
git add .
git commit -m "Your update message"
git push
```

Render will automatically detect the changes and redeploy your application.

## Troubleshooting

### Grid Not Displaying After CSV Load

**Symptoms:** File uploads successfully but data grid doesn't appear

**Solutions:**

1. **Check browser console (F12 → Console tab):**
   - Look for JavaScript errors
   - Check if "About to render grid..." message appears
   - Look for fetch errors to `/get_data`

2. **Session Issues:**
   - Session might have expired (Render free tier spins down)
   - Try uploading again
   - This is normal on free tier - consider upgrading to Starter plan

3. **Render Logs:**
   - Go to Render Dashboard → Your Service → Logs
   - Look for errors in app/request logs
   - Check if session was properly created (`Session ... stored`)

### Session Error When Navigating to Mating Selection

**Symptoms:** "Hiba: Érvénytelen vagy lejárt munkamenet" (Session invalid or expired)

**Causes:**

1. **Free tier spin-down:** App went to sleep between navigation
2. **Memory issue:** Large databases may cause issues
3. **Race condition:** Session not fully created when accessing

**Solutions:**

1. **Immediate fix:**
   - Reload the page
   - Upload the file again
   - Try the mating selection again

2. **Permanent fix for production:**
   - Upgrade from Free to **Starter** plan ($7/month)
   - Starter plan doesn't spin down
   - Better resources for large pedigrees

3. **Check Render status:**
   - Look at Render dashboard logs
   - See if app shows "Restarting" or "Spinning down"

### Status Codes and What They Mean

- **200 OK:** Request successful
- **404 Not Found:** Session not found - likely expired (free tier)
- **500 Server Error:** Internal error - check logs
- **502 Bad Gateway:** App crashed or restarting

### Monitoring Your App

**Check health:**

```
https://your-app.onrender.com/health
```

Should return: `{"status": "ok", "sessions": N}`

**View logs:**

1. Render Dashboard → Your Service → Logs
2. Look for INFO messages about session creation
3. Look for ERROR messages about missing sessions

### Performance Issues on Free Tier

**Expected behavior:**

- First request: 30-60 seconds (spinning up)
- Subsequent requests: Normal speed
- After 15 minutes idle: Spins down again

**Acceptable workarounds:**

- Keep a tab open to prevent spin-down
- Use Render's automated wake-up between uses
- **Recommended:** Upgrade to Starter plan

### Memory Issues with Large Pedigrees

**Symptoms:**

- Slow uploads
- "Out of memory" errors
- Session lost during calculation

**Solutions:**

1. Try with smaller CSV (~5,000 animals)
2. Check Render dashboard for memory usage
3. Consider upgrading plan for more resources
4. For very large datasets (100K+ animals):
   - May need Standard plan or dedicated resources
   - Consider optimizing pedigree data structure

### Database/Session Loss on Redeploy

**Expected behavior:**

- When you `git push`, Render automatically redeploys
- All in-memory sessions are lost
- Users must re-upload files

**Warning:** This is a known limitation for free tier. For production:

- Add Redis for session persistence
- Add database backend
- See "Session Storage Warning" section below

## Session Storage Warning

⚠️ **Important:** The current app uses in-memory session storage (`app.sessions = {}`). This means:

## Alternative Deployment Options

If Render.com doesn't meet your needs, consider:

- **Heroku** - Similar platform, easy deployment
- **Railway** - Modern platform with free tier
- **Google Cloud Run** - Pay-per-use, scales to zero
- **AWS Elastic Beanstalk** - AWS managed service
- **DigitalOcean App Platform** - Simple deployment
- **Fly.io** - Global edge deployment

## Support

For Render.com specific issues, visit:

- Documentation: https://render.com/docs
- Community: https://community.render.com
- Support: https://render.com/support
