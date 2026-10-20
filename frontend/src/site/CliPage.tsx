import { CheckCircle2, Download, Plane, Route, TerminalSquare } from "lucide-react";

import type { WebsiteRelease } from "./release";

interface CliPageProps {
  release: WebsiteRelease;
}

const commandGroups = [
  {
    icon: CheckCircle2,
    eyebrow: "START HERE",
    title: "Check your workspace",
    body: "Verify the account, Agent Core, Runtime, model access, maps, and aircraft before a mission begins.",
    commands: [
      ["dronedream doctor", "Run the complete readiness check."],
      ["dronedream runtime status", "Inspect the product-managed Runtime."],
      ["dronedream runtime setup", "Prepare the Runtime when it is missing."],
      ["dronedream models", "List the managed models available to this account."],
    ],
  },
  {
    icon: Route,
    eyebrow: "CHOOSE REAL ASSETS",
    title: "Find a map and aircraft",
    body: "Read the installed catalog first, then inspect the combinations qualified for a real simulation run.",
    commands: [
      ["dronedream assets maps", "List maps and their resource identifiers."],
      ["dronedream assets aircraft", "List aircraft and their resource identifiers."],
      ["dronedream assets pairs --map <map-id>", "Show aircraft qualified for one map."],
      ["dronedream assets pairs --aircraft <aircraft-id>", "Show maps qualified for one aircraft."],
    ],
  },
  {
    icon: Plane,
    eyebrow: "PLAN AND FLY",
    title: "Give the agent a mission",
    body: "The flight command sends natural language to the configured model, presents selectors when details are missing, and starts only after review.",
    commands: [
      ['dronedream mission fly "Inspect the library entrance, then return."', "Use the interactive model, map, and aircraft selectors."],
      ['dronedream mission fly "Carry the package to the lab." --model <model-id> --map <map-id> --aircraft <aircraft-id>', "Choose every resource explicitly."],
      ['dronedream mission fly "Check the roof." --plan-only', "Create and review the plan without launching simulation."],
      ["dronedream mission watch <thread-id>", "Follow phases and completion from another terminal."],
    ],
  },
  {
    icon: TerminalSquare,
    eyebrow: "OBSERVE AND RETURN",
    title: "Inspect the run and history",
    body: "Read telemetry, capture a live frame, continue a conversation, and return to any saved mission later.",
    commands: [
      ["dronedream mission telemetry <thread-id>", "Read current simulation telemetry."],
      ["dronedream mission frame <thread-id> --output flight.png", "Save a new live PNG frame."],
      ['dronedream mission message <thread-id> --text "Move the inspection closer to the east wall."', "Continue the mission conversation."],
      ["dronedream history list --archived-only", "List archived mission records."],
      ["dronedream history show <thread-id>", "Open one saved mission record."],
      ["dronedream history export <thread-id> --output mission.json", "Export one mission record."],
    ],
  },
] as const;

export function CliPage({ release }: CliPageProps) {
  const installerCommand = `Invoke-WebRequest -Uri "${release.downloadUrl}" -OutFile "$env:TEMP\\${release.fileName}"; Start-Process "$env:TEMP\\${release.fileName}"`;

  return (
    <section className="site-cli-page" aria-labelledby="cli-page-title">
      <header className="site-cli-hero">
        <p>DRONEDREAM IN YOUR TERMINAL</p>
        <h1 id="cli-page-title">One command line.<br />The complete flight.</h1>
        <span>
          Choose real assets, describe the work in natural language, review the model-built route,
          run PX4 and Gazebo, and return to the saved mission without opening the desktop interface.
        </span>
        <div className="site-cli-install">
          <div>
            <Download aria-hidden="true" />
            <strong>Install Universal and the CLI</strong>
            <small>Windows 10 / 11 · x64</small>
          </div>
          <code>{installerCommand}</code>
        </div>
      </header>

      <div className="site-cli-groups">
        {commandGroups.map((group) => {
          const Icon = group.icon;
          return (
            <article className="site-cli-group" key={group.title}>
              <div className="site-cli-group-copy">
                <Icon aria-hidden="true" />
                <p>{group.eyebrow}</p>
                <h2>{group.title}</h2>
                <span>{group.body}</span>
              </div>
              <div className="site-cli-command-list">
                {group.commands.map(([command, description]) => (
                  <div className="site-cli-command" key={command}>
                    <code><b aria-hidden="true">$</b> {command}</code>
                    <span>{description}</span>
                  </div>
                ))}
              </div>
            </article>
          );
        })}
      </div>

      <footer className="site-cli-footer-note">
        <strong>Need the complete option list?</strong>
        <code>dronedream --help</code>
        <code>dronedream mission fly --help</code>
        <span>Add <code>--json</code> for scripts or <code>--no-color</code> for a plain terminal.</span>
      </footer>
    </section>
  );
}
