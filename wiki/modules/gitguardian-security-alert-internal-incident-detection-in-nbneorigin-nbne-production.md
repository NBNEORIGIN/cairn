# GitGuardian Security Alert: Internal Incident Detection in NBNEORIGIN/nbne_production

## Summary

GitGuardian has detected an internal security incident in the `NBNEORIGIN/nbne_production` repository. This alert indicates that sensitive credentials, API keys, or other secrets may have been committed to the codebase. Immediate action is required to rotate compromised credentials, remove secrets from Git history, and prevent future incidents through proper secrets management practices.

## Immediate Response Steps

### 1. Assess the Incident

- **Check the GitGuardian dashboard** to identify the specific secret type detected (API key, password, token, certificate, etc.)
- **Identify the commit hash** where the secret was exposed
- **Determine the scope**: Note which files contain the leaked credentials and when they were committed
- **Review access logs**: Check if the exposed credentials have been accessed or used by unauthorized parties

### 2. Rotate Compromised Credentials

**⚠️ WARNING**: This is the most critical step. Assume any exposed secret has been compromised.

- **Immediately revoke or rotate** the exposed credentials through their respective service providers
- For API keys: Generate new keys in the service console and revoke old ones
- For passwords: Force password reset and implement MFA if not already enabled
- For database credentials: Update passwords in the database and all dependent services
- **Document which credentials were rotated** in the incident ticket

### 3. Remove Secrets from Git History

Simply deleting secrets in a new commit is **NOT sufficient** - they remain in Git history.

**Option A: Using BFG Repo-Cleaner (Recommended)**
```bash
# Clone a fresh copy
git clone --mirror git@github.com:NBNEORIGIN/nbne_production.git

# Remove the secret file or pattern
bfg --delete-files secret_file.env nbne_production.git
# OR use pattern matching
bfg --replace-text passwords.txt nbne_production.git

# Force push cleaned history
cd nbne_production.git
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
```

**Option B: Using git-filter-branch**
```bash
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch path/to/secret/file" \
  --prune-empty --tag-name-filter cat -- --all
git push --force --all
```

### 4. Notify and Coordinate

- **Alert the security team** immediately via #security-incidents Slack channel
- **Notify repository maintainers** who need to pull the cleaned history
- **Inform dependent services** that may need configuration updates after credential rotation
- All team members with local clones must run:
  ```bash
  git fetch origin
  git reset --hard origin/main
  ```

## Prevention Measures

### Implement Secrets Management

1. **Use environment variables** for all credentials - never hardcode
2. **Adopt a secrets manager**: Implement HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault
3. **Configure pre-commit hooks** with GitGuardian or git-secrets:
   ```bash
   pip install ggshield
   ggshield install --mode local
   ```

### Update .gitignore

Add common secret file patterns to your `.gitignore`:
```
.env
.env.*
*.pem
*.key
*credentials*
*secrets*
config/database.yml
```

### Repository Protection

- **Enable branch protection** rules requiring review before merge
- **Configure GitGuardian** to scan all pull requests automatically
- **Implement CODEOWNERS** file to require security team review for configuration changes

## Common Pitfalls

- **❌ Assuming deletion removes secrets**: Secrets remain in Git history even after file deletion
- **❌ Only rotating one environment**: Rotate credentials across ALL environments (dev, staging, prod)
- **❌ Forgetting dependent services**: Update all services that use the rotated credentials
- **❌ Not forcing team re-clone**: Team members with old clones still have secrets locally
- **❌ Ignoring monitoring**: Check service logs for unauthorized access attempts using compromised credentials

## Post-Incident Review

Within 48 hours of resolution:

1. Complete incident report in Jira under project SECURITY
2. Schedule post-mortem with affected team members
3. Update runbooks with lessons learned
4. Verify all prevention measures are implemented

## Related Topics

- **Secrets Management Best Practices** - Comprehensive guide to handling credentials
- **GitGuardian Integration Guide** - Setup and configuration documentation
- **Pre-commit Hook Configuration** - Preventing secrets from being committed
- **Emergency Credential Rotation Procedures** - Service-specific rotation guides
- **Security Incident Response Playbook** - General security incident handling