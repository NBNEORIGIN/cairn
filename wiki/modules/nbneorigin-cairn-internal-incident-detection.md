# NBNEORIGIN/cairn - Internal Incident Detection

## Summary

GitGuardian has detected an internal security incident within the NBNEORIGIN/cairn repository. This alert indicates that sensitive credentials, secrets, or security tokens may have been exposed in code commits. As a Cairn operator, immediate action is required to assess the exposure, rotate compromised credentials, and implement remediation steps to prevent similar incidents.

## Incident Response Steps

### 1. Access the Alert Details

Navigate to your GitGuardian dashboard to review the full incident details. The email notification contains limited information due to HTML rendering - you'll need to access the complete alert through the GitGuardian interface to identify:

- The specific file(s) containing exposed secrets
- The commit hash where the exposure occurred
- The type of secret detected (API key, token, password, certificate, etc.)
- The repository branch affected

### 2. Assess the Severity

Determine the impact level of the exposed credential:

- **Critical**: Production API keys, database credentials, signing certificates
- **High**: Development/staging credentials with production access
- **Medium**: Service tokens with limited scope
- **Low**: Test credentials or already-expired tokens

### 3. Immediate Containment

**⚠️ WARNING**: Do not simply delete the file or revert the commit. Git history retains all changes, meaning the secret remains accessible.

Take these actions immediately:

1. **Rotate the exposed credential** - Generate a new secret and update all services using it
2. **Revoke the compromised credential** - Invalidate the old secret in the service provider's console
3. **Audit access logs** - Check if the exposed credential was accessed or used maliciously
4. **Document the timeline** - Note when the secret was committed and when it was rotated

### 4. Remove Secret from Git History

Use one of these approaches to permanently remove the secret:

**Option A: BFG Repo-Cleaner (Recommended)**
```bash
bfg --replace-text passwords.txt NBNEORIGIN/cairn.git
cd NBNEORIGIN/cairn.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**Option B: git filter-branch**
```bash
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch PATH/TO/FILE" \
  --prune-empty --tag-name-filter cat -- --all
```

**⚠️ CRITICAL**: Coordinate with all team members before rewriting history. Force-pushing will affect anyone with local clones of the repository.

### 5. Implement Prevention Measures

Add protection layers to prevent future incidents:

- **Pre-commit hooks**: Install GitGuardian's ggshield or similar tools locally
  ```bash
  pip install ggshield
  ggshield install -m local
  ```
- **Environment variables**: Store all secrets in environment variables or secret management systems
- **Secret scanning CI/CD**: Add GitGuardian scanning to your CI pipeline
- **.gitignore updates**: Ensure all credential files are excluded from version control

### 6. Team Communication

Once containment is complete:

1. Notify the security team of the incident and resolution
2. Brief all repository contributors on what happened
3. Update team documentation on secret management practices
4. Schedule a post-incident review if the exposure was critical

## Common Pitfalls

- **Deleting commits without rotating credentials**: The secret remains valid and exploitable
- **Only rotating in one environment**: Ensure all environments (dev, staging, prod) are updated
- **Ignoring the alert**: Automated scanners may have already detected and harvested the secret
- **Not checking forked repositories**: Public forks may contain the exposed secret even after cleanup

## Post-Incident Actions

- Mark the incident as resolved in GitGuardian once all steps are complete
- Update your secrets inventory to track which credentials were affected
- Review and update access controls for the compromised service
- Consider implementing HashiCorp Vault or AWS Secrets Manager for centralized secret management

## Related Topics

- **Cairn Secret Management Best Practices** - Standard procedures for handling credentials in Cairn deployments
- **GitGuardian Dashboard Guide** - Detailed walkthrough of alert management and configuration
- **NBNE Security Incident Response Protocol** - Escalation procedures for security events
- **Pre-commit Hook Configuration** - Setting up local secret scanning for all NBNE repositories
- **Git History Rewriting Guide** - Advanced techniques for removing sensitive data from repositories