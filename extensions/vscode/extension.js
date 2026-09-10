// @ts-check
'use strict';

/**
 * DevRepro Doctor in the editor.
 *
 * Three design decisions, each of which is the difference between an extension
 * people keep and one they disable in week two.
 *
 * **It does not scan on startup.** A scan takes seconds and spawns processes,
 * and an editor extension that does that while somebody is opening a file is an
 * extension they uninstall. `devrepro.scanOnStartup` exists and defaults off.
 *
 * **Findings become diagnostics only where a file is genuinely involved.** Most
 * of what this tool reports is about the *machine* -- a stopped Docker daemon
 * is not a property of any line of code. Anchoring those to line 1 of some file
 * is how squiggles become noise people learn to ignore. Machine findings go to
 * the status bar and the output channel instead.
 *
 * **It shells out and parses JSON.** No language server, no daemon, no
 * long-lived process. `devrepro` already has a stable `--json` contract with a
 * published version -- `devrepro contract` -- and reusing it means this
 * extension has nothing of its own to keep in step.
 *
 * Plain CommonJS with JSDoc rather than TypeScript: no compiler, no bundler, no
 * pinned `vscode.d.ts`. The folder loads directly with
 * `code --extensionDevelopmentPath=extensions/vscode`.
 */

const vscode = require('vscode');
const { execFile } = require('node:child_process');
const path = require('node:path');

/** Severity mapping. `Hint` for INFO, so an informational finding does not
 * decorate the file like a problem. */
const SEVERITY = {
  BLOCKED: vscode.DiagnosticSeverity.Error,
  ERROR: vscode.DiagnosticSeverity.Error,
  WARN: vscode.DiagnosticSeverity.Warning,
  INFO: vscode.DiagnosticSeverity.Hint,
  UNKNOWN: vscode.DiagnosticSeverity.Information,
};

/**
 * Run devrepro and parse its JSON.
 *
 * @param {string[]} args
 * @param {string} cwd
 * @returns {Promise<any>}
 */
function run(args, cwd) {
  const exe = vscode.workspace.getConfiguration('devrepro').get('executable', 'devrepro');
  return new Promise((resolve, reject) => {
    execFile(exe, args, { cwd, maxBuffer: 32 * 1024 * 1024 }, (error, stdout, stderr) => {
      // A non-zero exit is the *contract*, not a failure: 1 means warnings and
      // 2 means blocked. Rejecting on it would turn a working scan into an
      // error notification.
      if (error && !stdout) {
        reject(new Error(stderr || String(error)));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (parseError) {
        reject(new Error(`devrepro did not return JSON: ${String(parseError)}`));
      }
    });
  });
}

/**
 * The repository-relative path a finding is genuinely about, or null.
 *
 * Absolute paths are refused. An evidence path may be `/usr/bin/python3` or
 * inside somebody's home directory, and a diagnostic anchored there is both
 * meaningless in the editor and a username on screen during a screen-share.
 *
 * @param {any} finding
 * @returns {string | null}
 */
function fileFor(finding) {
  for (const evidence of finding.evidence || []) {
    const candidate = evidence.path;
    if (!candidate) continue;
    if (candidate.startsWith('/') || candidate.startsWith('~')) continue;
    if (candidate.length > 1 && candidate[1] === ':') continue;
    return candidate.replace(/\\/g, '/');
  }
  return null;
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection('devrepro');
  const output = vscode.window.createOutputChannel('DevRepro Doctor');
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = 'devrepro.scan';
  status.text = '$(pulse) DevRepro';
  status.tooltip = 'Scan this machine';
  status.show();

  context.subscriptions.push(diagnostics, output, status);

  async function scan() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      vscode.window.showWarningMessage('DevRepro: open a folder first.');
      return;
    }

    status.text = '$(sync~spin) DevRepro';
    try {
      const report = await run(['doctor', '--json'], folder.uri.fsPath);
      const findings = report.findings || [];

      /** @type {Map<string, vscode.Diagnostic[]>} */
      const byFile = new Map();
      let machineFindings = 0;
      let worst = 'PASS';

      output.clear();
      for (const finding of findings) {
        if (finding.state === 'BLOCKED' || finding.state === 'ERROR') worst = 'BLOCKED';
        else if (worst === 'PASS' && (finding.state === 'WARN' || finding.state === 'UNKNOWN')) {
          worst = 'WARN';
        }

        const relative = fileFor(finding);
        if (!relative) {
          machineFindings += 1;
          output.appendLine(`[${finding.state}] ${finding.rule_id}: ${finding.summary}`);
          if (finding.remediation_hint) output.appendLine(`    ${finding.remediation_hint}`);
          continue;
        }

        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(0, 0, 0, 0),
          `${finding.summary}${finding.remediation_hint ? `\n\n${finding.remediation_hint}` : ''}`,
          SEVERITY[finding.state] ?? vscode.DiagnosticSeverity.Information,
        );
        diagnostic.source = 'devrepro';
        // The rule id is the stable part of the contract, so it is what a
        // reader should be able to search for and quote.
        diagnostic.code = finding.rule_id;
        const list = byFile.get(relative) || [];
        list.push(diagnostic);
        byFile.set(relative, list);
      }

      diagnostics.clear();
      for (const [relative, list] of byFile) {
        diagnostics.set(vscode.Uri.file(path.join(folder.uri.fsPath, relative)), list);
      }

      const icon = worst === 'BLOCKED' ? '$(error)' : worst === 'WARN' ? '$(warning)' : '$(check)';
      status.text = `${icon} DevRepro`;
      status.tooltip = `${findings.length} finding(s); ${machineFindings} about this machine rather than a file`;
      if (machineFindings > 0) {
        // Shown rather than silently filed: the machine findings are usually
        // the ones that matter, and they are the ones with nowhere in the
        // editor to appear.
        output.appendLine('');
        output.appendLine(
          `${machineFindings} finding(s) are about this machine rather than a file, so they are ` +
            'listed here instead of being anchored to a line that has nothing to do with them.',
        );
      }
    } catch (error) {
      status.text = '$(error) DevRepro';
      output.appendLine(String(error));
      vscode.window.showErrorMessage(`DevRepro: ${String(error)}`);
    }
  }

  async function explain() {
    const ruleId = await vscode.window.showInputBox({
      prompt: 'Rule id, e.g. node/version-mismatch',
      placeHolder: 'prefix/name',
    });
    if (!ruleId) return;
    const folder = vscode.workspace.workspaceFolders?.[0];
    try {
      const doc = await run(['explain', ruleId, '--json'], folder ? folder.uri.fsPath : process.cwd());
      const rendered = [
        `# ${doc.rule_id}`,
        '',
        `## ${doc.title}`,
        '',
        `**What it means** — ${doc.means}`,
        '',
        `**Why it matters** — ${doc.matters}`,
        '',
        `**How to fix it** — ${doc.fix}`,
      ].join('\n');
      const document = await vscode.workspace.openTextDocument({
        content: rendered,
        language: 'markdown',
      });
      await vscode.window.showTextDocument(document, { preview: true });
    } catch (error) {
      vscode.window.showErrorMessage(`DevRepro: ${String(error)}`);
    }
  }

  async function agentCheck() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) return;
    try {
      const result = await run(['agent-check', '.', '--json'], folder.uri.fsPath);
      const readiness = result.readiness || {};
      output.clear();
      output.appendLine(`Agent readiness: ${readiness.percent}% (${readiness.grade})`);
      for (const factor of readiness.factors || []) {
        output.appendLine(`  [${factor.earned}/${factor.possible}] ${factor.name}: ${factor.explanation}`);
      }
      output.show(true);
    } catch (error) {
      vscode.window.showErrorMessage(`DevRepro: ${String(error)}`);
    }
  }

  context.subscriptions.push(
    vscode.commands.registerCommand('devrepro.scan', scan),
    vscode.commands.registerCommand('devrepro.explain', explain),
    vscode.commands.registerCommand('devrepro.agentCheck', agentCheck),
  );

  if (vscode.workspace.getConfiguration('devrepro').get('scanOnStartup', false)) {
    void scan();
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
