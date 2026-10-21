import { useState } from "react";
import {
  Check,
  CheckCircle2,
  Copy,
  Download,
  Plane,
  Route,
  TerminalSquare,
  type LucideIcon,
} from "lucide-react";

import type { WebsiteRelease } from "./release";

interface CliPageProps {
  release: WebsiteRelease;
}

interface CommandGroup {
  icon: LucideIcon;
  title: string;
  commands: readonly (readonly [command: string, description: string])[];
}

const commandGroups: readonly CommandGroup[] = [
  {
    icon: CheckCircle2,
    title: "Check Your Workspace",
    commands: [
      ["dronedream doctor", "Run the complete readiness check."],
      ["dronedream runtime status", "Inspect the managed Runtime."],
      ["dronedream runtime setup", "Prepare a missing Runtime."],
      ["dronedream models", "List available managed models."],
    ],
  },
  {
    icon: Route,
    title: "Choose a Map and Aircraft",
    commands: [
      ["dronedream assets maps", "List maps and resource identifiers."],
      ["dronedream assets aircraft", "List aircraft and resource identifiers."],
      ["dronedream assets pairs --map <map-id>", "Find aircraft qualified for a map."],
      ["dronedream assets pairs --aircraft <aircraft-id>", "Find maps qualified for an aircraft."],
    ],
  },
  {
    icon: Plane,
    title: "Plan and Fly",
    commands: [
      ['dronedream mission fly "Inspect the library entrance, then return."', "Choose resources interactively and begin."],
      ['dronedream mission fly "Carry the package to the lab." --model <model-id> --map <map-id> --aircraft <aircraft-id>', "Choose every resource explicitly."],
      ['dronedream mission fly "Check the roof." --plan-only', "Review the plan without launching."],
      ["dronedream mission watch <thread-id>", "Follow a mission from another terminal."],
    ],
  },
  {
    icon: TerminalSquare,
    title: "Watch and Reopen Missions",
    commands: [
      ["dronedream mission telemetry <thread-id>", "Read current simulation telemetry."],
      ["dronedream mission frame <thread-id> --output flight.png", "Save the newest live frame."],
      ['dronedream mission message <thread-id> --text "Move closer to the east wall."', "Continue the mission conversation."],
      ["dronedream history list --archived-only", "List archived mission records."],
      ["dronedream history show <thread-id>", "Open one saved mission."],
      ["dronedream history export <thread-id> --output mission.json", "Export one mission record."],
    ],
  },
] as const;

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function CliCommand({ command, description }: { command: string; description: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyText(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="site-cli-command">
      <div className="site-cli-command-box">
        <code><b aria-hidden="true">$</b> {command}</code>
        <button
          type="button"
          className={copied ? "is-copied" : undefined}
          aria-label={copied ? "Copied" : `Copy command: ${command}`}
          onClick={() => void handleCopy()}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        </button>
      </div>
      <span>{description}</span>
    </div>
  );
}

function CliModule({ icon: Icon, title, commands }: CommandGroup) {
  return (
    <article className="site-cli-group">
      <h2><Icon aria-hidden="true" /><span>{title}</span></h2>
      <div className="site-cli-command-list">
        {commands.map(([command, description]) => (
          <CliCommand command={command} description={description} key={command} />
        ))}
      </div>
    </article>
  );
}

export function CliPage({ release }: CliPageProps) {
  const installerCommand = `Invoke-WebRequest -Uri "${release.downloadUrl}" -OutFile "$env:TEMP\\${release.fileName}"; Start-Process "$env:TEMP\\${release.fileName}"`;

  return (
    <section className="site-cli-page" aria-labelledby="cli-page-title">
      <header className="site-cli-hero">
        <h1 id="cli-page-title">Hey! Command Your Flight.</h1>
      </header>

      <div className="site-cli-groups">
        <CliModule
          icon={Download}
          title="Install Universal and the CLI"
          commands={[[installerCommand, "Download and start the Universal installer."]]}
        />
        {commandGroups.map((group) => <CliModule {...group} key={group.title} />)}
      </div>

      <footer className="site-cli-footer-note">
        <strong>More options</strong>
        <CliCommand command="dronedream --help" description="Open the complete command index." />
        <CliCommand command="dronedream mission fly --help" description="Inspect every flight option." />
      </footer>
    </section>
  );
}
