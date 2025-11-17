# GitHub Pages Deployment Guide

This guide explains how to deploy PyEventEngine documentation to GitHub Pages, both manually and automatically via GitHub Actions.

## Table of Contents

- [Quick Start](#quick-start)
- [Automatic Deployment](#automatic-deployment)
- [Manual Deployment](#manual-deployment)
- [Version-Tagged Releases](#version-tagged-releases)
- [Custom Domain Setup](#custom-domain-setup)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

The documentation is automatically deployed on every push to `main`/`master` or when a version tag is pushed.

**Your documentation will be available at:**
```
https://<username>.github.io/<repository>/
```

For example:
```
https://bolunhan.github.io/PyEventEngine/
```

---

## Automatic Deployment

The repository includes a GitHub Actions workflow (`.github/workflows/docs.yml`) that automatically builds and deploys documentation.

### Triggers

The workflow runs on:

1. **Push to main/master branches**
   ```bash
   git push origin main
   ```

2. **Version tags** (format: `v*.*.*`)
   ```bash
   git tag v0.4.3
   git push origin v0.4.3
   ```

3. **Pull requests** (build only, no deployment)
   ```bash
   # Triggered automatically on PR creation/update
   ```

4. **Manual trigger** (via GitHub UI)
   - Go to Actions tab → Documentation workflow → Run workflow

### First-Time Setup

#### Step 1: Enable GitHub Pages

1. Go to your repository on GitHub
2. Click **Settings** (top menu bar)
3. In the left sidebar, scroll down and click **Pages**
4. Under **Source**, select:
   - **Source**: `Deploy from a branch`
   - **Branch**: `gh-pages`
   - **Folder**: `/ (root)`
5. Click **Save**

![GitHub Pages Settings](https://docs.github.com/assets/cb-47267/images/help/pages/select-branch.png)

#### Step 2: Push to Trigger Workflow

```bash
# Make sure your changes are committed
git add .
git commit -m "Add documentation"

# Push to main branch
git push origin main

# Or push a version tag
git tag v0.4.3
git push origin v0.4.3
```

#### Step 3: Wait for Deployment

1. Go to **Actions** tab in your repository
2. You should see a "Documentation" workflow running
3. Wait for it to complete (usually 1-3 minutes)
4. Once complete, go to **Settings → Pages** to see your site URL

#### Step 4: Verify Deployment

Visit your documentation site:
```
https://<username>.github.io/<repository>/
```

---

## Manual Deployment

If you need to deploy manually (without GitHub Actions):

### Prerequisites

```bash
pip install ghp-import sphinx furo
pip install -e .  # Install package for autodoc
```

### Build and Deploy

```bash
# Build documentation
cd docs
make html

# Deploy to gh-pages branch
ghp-import -n -p -f _build/html -m "Deploy documentation manually"
```

The `-n` flag adds a `.nojekyll` file (required for Sphinx), `-p` pushes to remote, and `-f` forces the update.

### Verify

Check your GitHub Pages URL:
```
https://<username>.github.io/<repository>/
```

---

## Version-Tagged Releases

### Creating a Version Tag

When you release a new version, tag it to trigger documentation deployment:

```bash
# Make sure you're on the main branch with latest code
git checkout main
git pull origin main

# Update version in your code (e.g., event_engine/__init__.py)
# Update version in docs/conf.py if needed

# Commit version bump
git add event_engine/__init__.py docs/conf.py
git commit -m "Bump version to v0.4.3"

# Create and push tag
git tag -a v0.4.3 -m "Release version 0.4.3"
git push origin main
git push origin v0.4.3
```

### Tag Format

The workflow triggers on tags matching `v*.*.*`:
- ✅ `v0.4.3` - Triggers deployment
- ✅ `v1.0.0` - Triggers deployment
- ✅ `v1.2.3-rc1` - Triggers deployment
- ❌ `0.4.3` - Does NOT trigger (missing 'v' prefix)
- ❌ `release-0.4.3` - Does NOT trigger (wrong format)

### Viewing Tag Deployments

1. Go to **Actions** tab
2. Filter by "Documentation" workflow
3. You'll see deployments for both branch pushes and tags
4. Each deployment shows which ref (branch/tag) triggered it

---

## Custom Domain Setup

To use a custom domain (e.g., `docs.pyeventengine.com`):

### Step 1: Update GitHub Workflow

Edit `.github/workflows/docs.yml`:

```yaml
- name: Deploy to GitHub Pages
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./docs/_build/html
    cname: docs.pyeventengine.com  # Add your custom domain here
```

### Step 2: Configure DNS

Add a CNAME record in your DNS provider:

```
Type: CNAME
Name: docs (or whatever subdomain you want)
Value: <username>.github.io
```

For apex domain (e.g., `pyeventengine.com`), use A records instead:

```
Type: A
Name: @
Value: 185.199.108.153
       185.199.109.153
       185.199.110.153
       185.199.111.153
```

### Step 3: Enable HTTPS

1. Go to **Settings → Pages**
2. Wait for DNS to propagate (can take up to 24 hours)
3. Check **Enforce HTTPS**

---

## Troubleshooting

### Build Fails in GitHub Actions

**Check the Actions log:**
1. Go to **Actions** tab
2. Click on the failed workflow run
3. Expand the failed step to see error details

**Common issues:**

- **Import errors**: Ensure `pip install -e .` succeeds
  ```yaml
  - run: pip install -e . || pip install .
  ```

- **Missing dependencies**: Add to workflow
  ```yaml
  - run: pip install sphinx furo your-other-deps
  ```

- **Sphinx build errors**: Test locally first
  ```bash
  cd docs && make html
  ```

### Documentation Not Updating

**Clear your browser cache:**
- Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)

**Check deployment status:**
1. Go to **Actions** tab
2. Verify the workflow completed successfully
3. Check **Settings → Pages** for the build status

**Force rebuild:**
```bash
git commit --allow-empty -m "Trigger docs rebuild"
git push origin main
```

### 404 Error on GitHub Pages

**Ensure gh-pages branch exists:**
```bash
git ls-remote --heads origin gh-pages
```

If missing, the workflow will create it on first successful run.

**Check Pages settings:**
- Source must be `gh-pages` branch
- Folder must be `/ (root)`

### Workflow Not Triggering

**For branch pushes:**
```bash
# Ensure you're pushing to main or master
git branch --show-current
git push origin main
```

**For tags:**
```bash
# Ensure tag format is v*.*.*
git tag v0.4.3
git push origin v0.4.3

# Verify tag was pushed
git ls-remote --tags origin
```

### Permission Denied Errors

**Ensure repository has proper permissions:**
1. Go to **Settings → Actions → General**
2. Under **Workflow permissions**, select:
   - ✅ **Read and write permissions**
3. Save changes

### Build Succeeds But Site Is Broken

**Check for missing static files:**
```bash
# Build locally and inspect output
cd docs
make html
ls -la _build/html/_static/
```

**Verify Sphinx configuration:**
- Check `docs/conf.py` for errors
- Ensure `html_static_path = ['_static']` is set
- Verify theme is installed: `pip list | grep furo`

### Version Not Updating in Docs

**Update version in multiple places:**

1. `event_engine/__init__.py`:
   ```python
   __version__ = '0.4.3'
   ```

2. `docs/conf.py`:
   ```python
   release = 'v0.4.3'
   ```

3. Commit and push:
   ```bash
   git add event_engine/__init__.py docs/conf.py
   git commit -m "Bump version to v0.4.3"
   git tag v0.4.3
   git push origin main v0.4.3
   ```

---

## Advanced Configuration

### Multiple Documentation Versions

To maintain docs for multiple versions:

1. **Use sphinx-multiversion**:
   ```bash
   pip install sphinx-multiversion
   ```

2. **Update workflow**:
   ```yaml
   - name: Build multi-version docs
     run: sphinx-multiversion docs docs/_build/html
   ```

3. **Configure in `docs/conf.py`**:
   ```python
   extensions = ['sphinx_multiversion']
   smv_tag_whitelist = r'^v\d+\.\d+\.\d+$'
   ```

### Deployment Notifications

Add Slack/Discord notifications on deployment:

```yaml
- name: Notify on deployment
  if: success()
  run: |
    curl -X POST ${{ secrets.WEBHOOK_URL }} \
      -H 'Content-Type: application/json' \
      -d '{"text":"Docs deployed for ${{ github.ref_name }}"}'
```

### Preview Deployments for PRs

Deploy PR previews to a subdirectory:

```yaml
- name: Deploy PR preview
  if: github.event_name == 'pull_request'
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./docs/_build/html
    destination_dir: pr-${{ github.event.pull_request.number }}
```

---

## Summary

- ✅ **Automatic deployment** on push to main/master or version tags
- ✅ **Manual deployment** via `ghp-import` if needed
- ✅ **Version tagging** triggers documentation updates
- ✅ **GitHub Pages** hosts your docs for free
- ✅ **Custom domains** supported with CNAME
- ✅ **HTTPS** automatically provided by GitHub

For more help, see:
- [GitHub Pages Documentation](https://docs.github.com/en/pages)
- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)

