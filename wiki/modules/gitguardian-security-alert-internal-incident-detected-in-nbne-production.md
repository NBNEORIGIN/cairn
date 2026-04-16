# GitGuardian Security Alert: Internal Incident Detected in NBNE Production

## Summary

This alert indicates that GitGuardian has detected exposed credentials or secrets within the `NBNEORIGIN/nbne_production` repository. GitGuardian continuously scans commits, branches, and pull requests for API keys, passwords, tokens, certificates, and other sensitive information that should never be committed to version control. When triggered, this alert requires immediate action to rotate compromised credentials and remove secrets from the repository history.

## Immediate Response Steps

1. **Acknowledge the Alert**
   - Click through the email notification to view the full GitGuardian incident details
   - Note the specific file path, commit hash, and type of secret detected
   - Document the timestamp and scope of exposure

2. **Assess the Exposure**
   - Determine which credential type was exposed (API key, database password, token, etc.)
   - Check if the commit has been pushed to remote branches or is still local
   - Verify if the exposed secret is currently active in production systems

3. **Rotate the Compromised Credentials Immediately**
   - Generate new credentials in the affected service (AWS, database, API provider, etc.)
   - Update production systems with new credentials via secure configuration management
   - Revoke/disable the exposed credentials to prevent unauthorized access
   - **WARNING:** Do not skip rotation even if the commit seems recent. Assume the secret is compromised.

4. **Remove Secrets from Repository History**
   - Use `git filter-branch` or `BFG Repo Cleaner` to remove secrets from all commits
   - For recent commits on feature branches, consider force-pushing after removing the secret
   - Coordinate with team members before rewriting shared branch history
   - Example BFG command: `bfg --replace-text passwords.txt nbne_production.git`

5. **Update the Code Properly**
   - Move credentials to environment variables or secure secret management systems
   - Use Deek's approved secret management: AWS Secrets Manager or HashiCorp Vault
   - Update application code to retrieve secrets at runtime, not build time
   - Add affected file patterns to `.gitignore` to prevent future commits

6. **Close the GitGuardian Incident**
   - Mark the incident as resolved in GitGuardian dashboard once remediation is complete
   - Document remediation actions taken in the incident notes
   - If this is a false positive (e.g., dummy credentials in tests), mark accordingly

## Common Pitfalls

**⚠️ Deleting the file in a new commit does NOT remove it from history.** The secret remains accessible in previous commits and must be removed using history-rewriting tools.

**⚠️ Rotating credentials without removing them from history is incomplete.** While rotation limits immediate risk, the exposed credentials remain visible to anyone with repository access.

**⚠️ Don't commit new secrets while attempting to fix the issue.** Ensure replacement credentials are properly externalized, not hardcoded in new commits.

**⚠️ Force-pushing to shared branches affects all team members.** Coordinate with your team before rewriting history on main/develop branches. Consider protection rules.

## Prevention Best Practices

- **Use Pre-commit Hooks**: Install GitGuardian's pre-commit hooks or `git-secrets` locally to catch secrets before they're committed
- **Environment-based Configuration**: Store all secrets in environment variables or dedicated secret management systems
- **Code Reviews**: Train team members to spot hardcoded credentials during PR reviews
- **Template Files**: Use `.env.example` files with dummy values; never commit actual `.env` files
- **CI/CD Integration**: Ensure GitGuardian scans run in your pipeline before merging

## Repository-Specific Context for NBNE Production

The `NBNEORIGIN/nbne_production` repository is a critical production codebase. Any credential exposure here has immediate operational security implications:

- Production database credentials could expose customer data
- API keys may grant access to billing or third-party integrations
- AWS credentials could allow infrastructure manipulation
- Always follow the incident response protocol and notify the security team for production repository incidents

## Related Topics

- **Deek Security Policies**: Review organization-wide secret management standards
- **AWS Secrets Manager Integration**: Guide for retrieving secrets in NBNE applications
- **HashiCorp Vault Setup**: Alternative secret management for on-premise deployments
- **Git History Rewriting**: Detailed procedures for BFG Repo Cleaner and filter-branch
- **Incident Response Procedures**: Escalation paths for security incidents
- **Pre-commit Hook Installation**: Setting up local secret scanning tools