import * as vscode from 'vscode';
import { ClawPanel } from './panel';

// ─── Inline completion provider ──────────────────────────────────────────────

let _completionDebounce: ReturnType<typeof setTimeout> | undefined;

class ClawInlineCompletionProvider implements vscode.InlineCompletionItemProvider {
    async provideInlineCompletionItems(
        document: vscode.TextDocument,
        position: vscode.Position,
        _context: vscode.InlineCompletionContext,
        token: vscode.CancellationToken,
    ): Promise<vscode.InlineCompletionList | undefined> {
        return new Promise((resolve) => {
            if (_completionDebounce) {
                clearTimeout(_completionDebounce);
            }
            _completionDebounce = setTimeout(async () => {
                if (token.isCancellationRequested) {
                    resolve(undefined);
                    return;
                }

                const config = vscode.workspace.getConfiguration('claw');
                const apiUrl = config.get<string>('apiUrl', 'http://localhost:8765');
                const apiKey = config.get<string>('apiKey', '');
                const project = config.get<string>('defaultProject', 'claw');

                const prefix = document.getText(
                    new vscode.Range(new vscode.Position(0, 0), position)
                );
                const suffix = document.getText(
                    new vscode.Range(position, document.positionAt(document.getText().length))
                );

                try {
                    const res = await fetch(`${apiUrl}/complete`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-API-Key': apiKey,
                        },
                        body: JSON.stringify({
                            file_path: document.fileName,
                            prefix,
                            suffix,
                            project,
                            language: document.languageId,
                        }),
                        signal: AbortSignal.timeout(3000),
                    });

                    if (!res.ok) {
                        resolve(undefined);
                        return;
                    }

                    const data = await res.json() as { completion: string; tier: number };
                    if (!data.completion || data.tier === 0) {
                        resolve(undefined);
                        return;
                    }

                    resolve(new vscode.InlineCompletionList([
                        new vscode.InlineCompletionItem(
                            data.completion,
                            new vscode.Range(position, position),
                        ),
                    ]));
                } catch {
                    resolve(undefined);
                }
            }, 800);  // 800ms debounce
        });
    }
}

// ─── Extension activation ────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {

    // Register inline completion provider for all languages
    context.subscriptions.push(
        vscode.languages.registerInlineCompletionItemProvider(
            { pattern: '**' },
            new ClawInlineCompletionProvider(),
        )
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('claw.openPanel', () => {
            ClawPanel.createOrShow(context.extensionUri);
        }),

        vscode.commands.registerCommand('claw.newSession', () => {
            if (ClawPanel.currentPanel) {
                ClawPanel.currentPanel.newSession();
            } else {
                ClawPanel.createOrShow(context.extensionUri);
            }
        }),

        vscode.commands.registerCommand('claw.indexProject', async () => {
            const config = vscode.workspace.getConfiguration('claw');
            const apiUrl = config.get<string>('apiUrl', 'http://localhost:8765');
            const apiKey = config.get<string>('apiKey', '');
            const projectId = config.get<string>('defaultProject', '');

            if (!projectId) {
                vscode.window.showErrorMessage(
                    'Set claw.defaultProject in VS Code settings first'
                );
                return;
            }

            try {
                const res = await fetch(
                    `${apiUrl}/projects/${projectId}/index`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-API-Key': apiKey,
                        },
                        body: JSON.stringify({ force: false }),
                    }
                );
                if (res.ok) {
                    vscode.window.showInformationMessage(
                        `CLAW: Indexing ${projectId} started`
                    );
                } else {
                    vscode.window.showErrorMessage(
                        `CLAW: Indexing failed — ${res.status}`
                    );
                }
            } catch (err) {
                vscode.window.showErrorMessage(
                    `CLAW: Cannot reach API at ${apiUrl}`
                );
            }
        }),

        vscode.commands.registerCommand('claw.addMention', async () => {
            const config = vscode.workspace.getConfiguration('claw');
            const apiUrl = config.get<string>('apiUrl', 'http://localhost:8765');
            const apiKey = config.get<string>('apiKey', '');
            const projectId = config.get<string>('defaultProject', 'claw');

            // Step 1 — pick context type
            const typeChoice = await vscode.window.showQuickPick(
                [
                    { label: '📄 File', value: 'file', description: 'Pin a specific file' },
                    { label: '📁 Folder', value: 'folder', description: 'Pin all files in a folder' },
                    { label: '⚙ Symbol', value: 'symbol', description: 'Pin a function or class by name' },
                    { label: '💬 Session', value: 'session', description: 'Attach a past session' },
                    { label: '📌 core.md', value: 'core', description: 'Attach the project core.md' },
                    { label: '🌐 Web search', value: 'web', description: 'Search the web and attach results' },
                ],
                { placeHolder: 'What context do you want to pin?' },
            );
            if (!typeChoice) { return; }

            let value = '';
            let display = '';

            if (typeChoice.value === 'core') {
                value = 'core.md';
                display = 'core.md';
            } else if (typeChoice.value === 'web') {
                const query = await vscode.window.showInputBox({ prompt: 'Web search query' });
                if (!query) { return; }
                value = query;
                display = query.slice(0, 30);
            } else if (typeChoice.value === 'file' || typeChoice.value === 'folder') {
                try {
                    const res = await fetch(`${apiUrl}/projects/${projectId}/files`, {
                        headers: { 'X-API-Key': apiKey },
                    });
                    const data = await res.json() as { files: string[] };
                    let items = (data.files || []).map((f: string) => ({ label: f }));
                    if (typeChoice.value === 'folder') {
                        const dirs = new Set<string>();
                        data.files.forEach((f: string) => {
                            const parts = f.split('/');
                            if (parts.length > 1) { dirs.add(parts[0]); }
                        });
                        items = Array.from(dirs).map(d => ({ label: d + '/' }));
                    }
                    const picked = await vscode.window.showQuickPick(items, {
                        placeHolder: `Select a ${typeChoice.value}`,
                        matchOnDescription: true,
                    });
                    if (!picked) { return; }
                    value = picked.label.replace(/\/$/, '');
                    display = value.split('/').pop() || value;
                } catch {
                    vscode.window.showErrorMessage('CLAW: Could not fetch file list');
                    return;
                }
            } else if (typeChoice.value === 'symbol') {
                const query = await vscode.window.showInputBox({ prompt: 'Symbol name (function or class)' });
                if (!query) { return; }
                try {
                    const res = await fetch(
                        `${apiUrl}/projects/${projectId}/symbols?q=${encodeURIComponent(query)}`,
                        { headers: { 'X-API-Key': apiKey } },
                    );
                    const data = await res.json() as { symbols: Array<{ name: string; file: string; type: string }> };
                    if (!data.symbols?.length) {
                        vscode.window.showWarningMessage(`No symbols found matching "${query}"`);
                        return;
                    }
                    const picked = await vscode.window.showQuickPick(
                        data.symbols.map(s => ({ label: s.name, description: `${s.type} in ${s.file}` })),
                        { placeHolder: 'Select symbol' },
                    );
                    if (!picked) { return; }
                    value = picked.label;
                    display = picked.label;
                } catch {
                    vscode.window.showErrorMessage('CLAW: Could not fetch symbols');
                    return;
                }
            } else if (typeChoice.value === 'session') {
                try {
                    const res = await fetch(
                        `${apiUrl}/projects/${projectId}/sessions`,
                        { headers: { 'X-API-Key': apiKey } },
                    );
                    const data = await res.json() as { sessions: Array<{ session_id: string; first_message?: string }> };
                    const picked = await vscode.window.showQuickPick(
                        (data.sessions || []).map(s => ({
                            label: s.session_id.slice(0, 16),
                            description: s.first_message?.slice(0, 60) || '',
                            value: s.session_id,
                        })),
                        { placeHolder: 'Select session to attach' },
                    );
                    if (!picked) { return; }
                    value = (picked as any).value;
                    display = picked.label;
                } catch {
                    vscode.window.showErrorMessage('CLAW: Could not fetch sessions');
                    return;
                }
            }

            if (!value) { return; }

            // Send the mention to the panel
            if (ClawPanel.currentPanel) {
                ClawPanel.currentPanel.addMention({ type: typeChoice.value, value, display });
                vscode.window.showInformationMessage(`CLAW: Pinned ${typeChoice.value} — ${display}`);
            } else {
                vscode.window.showWarningMessage('CLAW panel is not open');
            }
        }),

        vscode.commands.registerCommand('claw.switchProject', async () => {
            const config = vscode.workspace.getConfiguration('claw');
            const apiUrl = config.get<string>('apiUrl', 'http://localhost:8765');
            const apiKey = config.get<string>('apiKey', '');

            try {
                const res = await fetch(`${apiUrl}/projects`, {
                    headers: { 'X-API-Key': apiKey },
                });
                const data = await res.json() as { projects: Array<{ id: string; name: string; ready: boolean }> };
                const items = data.projects
                    .filter(p => p.ready)
                    .map(p => ({ label: p.id, description: p.name }));

                const picked = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select CLAW project',
                });

                if (picked) {
                    await config.update(
                        'defaultProject', picked.label,
                        vscode.ConfigurationTarget.Global
                    );
                    if (ClawPanel.currentPanel) {
                        ClawPanel.currentPanel.switchProject(picked.label);
                    }
                    vscode.window.showInformationMessage(
                        `CLAW: Switched to project '${picked.label}'`
                    );
                }
            } catch {
                vscode.window.showErrorMessage(
                    `CLAW: Cannot reach API at ${apiUrl}`
                );
            }
        }),
    );
}

export function deactivate() {}
