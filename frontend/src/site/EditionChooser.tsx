import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import {
  isEditionDownloadReady,
  primaryEditionIds,
  type EditionAvailabilityDocument,
  type EditionId,
  type PrimaryEditionId,
} from "./editionAvailability";
import type { WebsiteRelease } from "./release";

type EditionChooserProps = {
  availability: EditionAvailabilityDocument;
  setCloseButtonRef: (node: HTMLButtonElement | null) => void;
  currentRelease: WebsiteRelease;
  setDialogRef: (node: HTMLElement | null) => void;
  locale: "en" | "zh-CN";
  onClose: () => void;
  open: boolean;
};

const chooserCopy = {
  en: {
    title: "Choose your edition",
    subtitle: "Pick the workspace that fits your next flight.",
    close: "Close edition chooser",
    recommended: "Recommended",
    select: "Select",
    confirm: "Confirm download",
    soon: "Coming soon",
    vehiclePacks: "Vehicle packs are configured later; none are validated yet.",
    universal: "Not sure which fits? DroneDream Universal lets you switch workspaces later.",
    chooseUniversal: "Choose Universal",
    currentTitle: "Current preview",
    currentBody: "The existing unsigned 1.0.0 preview remains available.",
    currentAction: "Download current preview",
    editions: {
      sim: {
        title: "Sim",
        audience: "For PX4/Gazebo studies",
        capabilities: ["Simulation workflow", "Evidence review", "Local Runtime"],
      },
      lab: {
        title: "Lab",
        audience: "For benches and flight labs",
        capabilities: ["Simulation + hardware", "Controlled trials", "Lab handoff"],
      },
      field: {
        title: "Field",
        audience: "For advanced field teams",
        capabilities: ["Vehicle execution", "Safety gates", "Operator review"],
      },
    },
  },
  "zh-CN": {
    title: "选择使用版本",
    subtitle: "按下一次飞行任务选择工作空间",
    close: "关闭版本选择",
    recommended: "推荐",
    select: "选择",
    confirm: "确认下载",
    soon: "准备中",
    vehiclePacks: "机型包稍后配置，目前尚无通过验证的版本",
    universal: "不确定选哪个？下载 DroneDream Universal，可稍后切换模式",
    chooseUniversal: "选择 Universal",
    currentTitle: "当前内测版",
    currentBody: "现有未签名 1.0.0 内测版仍可下载",
    currentAction: "下载当前内测版",
    editions: {
      sim: {
        title: "仿真版",
        audience: "适合 PX4 / Gazebo 研究",
        capabilities: ["仿真调优流程", "证据审查", "本地 Runtime"],
      },
      lab: {
        title: "实验室版",
        audience: "适合台架与飞行实验室",
        capabilities: ["仿真与真机", "受控试验", "实验室交接"],
      },
      field: {
        title: "真机版",
        audience: "适合高级外场团队",
        capabilities: ["真机执行", "安全门禁", "操作员复核"],
      },
    },
  },
} as const;

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v11m0 0 4-4m-4 4-4-4M5 20h14" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m6 6 12 12M18 6 6 18" />
    </svg>
  );
}

export function EditionChooser({
  availability,
  setCloseButtonRef,
  currentRelease,
  setDialogRef,
  locale,
  onClose,
  open,
}: EditionChooserProps) {
  const [selectedId, setSelectedId] = useState<EditionId | null>(null);
  const choiceRefs = useRef(new Map<PrimaryEditionId, HTMLButtonElement>());
  const copy = chooserCopy[locale];
  const primaryEditions = availability.editions.filter(
    (edition): edition is typeof edition & { id: PrimaryEditionId } => (
      primaryEditionIds.includes(edition.id as PrimaryEditionId)
    ),
  );
  const universalEdition = availability.editions.find(({ id }) => id === "universal");
  const selectedPrimaryId = selectedId && primaryEditionIds.includes(selectedId as PrimaryEditionId)
    ? selectedId as PrimaryEditionId
    : null;

  useEffect(() => {
    if (open) setSelectedId(null);
  }, [open]);

  if (!open) return null;

  const moveSelection = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentId: PrimaryEditionId,
  ) => {
    const currentIndex = primaryEditions.findIndex(({ id }) => id === currentId);
    if (currentIndex < 0) return;
    let nextIndex: number;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % primaryEditions.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + primaryEditions.length) % primaryEditions.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = primaryEditions.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    const nextId = primaryEditions[nextIndex]?.id;
    if (!nextId) return;
    setSelectedId(nextId);
    choiceRefs.current.get(nextId)?.focus();
  };

  return (
    <div
      className="site-edition-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={setDialogRef}
        className="site-edition-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="site-edition-title"
        aria-describedby="site-edition-subtitle"
        tabIndex={-1}
      >
        <header className="site-edition-header">
          <div>
            <p className="site-eyebrow">DRONEDREAM EDITIONS</p>
            <h2 id="site-edition-title">{copy.title}</h2>
            <p id="site-edition-subtitle">{copy.subtitle}</p>
          </div>
          <button
            ref={setCloseButtonRef}
            type="button"
            className="site-edition-close"
            aria-label={copy.close}
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </header>

        <div className="site-edition-grid" role="radiogroup" aria-label={copy.title}>
          {primaryEditions.map((edition) => {
            const editionCopy = copy.editions[edition.id];
            const selected = selectedId === edition.id;
            const ready = isEditionDownloadReady(edition);
            return (
              <article
                key={edition.id}
                className="site-edition-card"
                data-edition={edition.id}
                data-selected={selected || undefined}
              >
                <button
                  ref={(node) => {
                    if (node) choiceRefs.current.set(edition.id, node);
                    else choiceRefs.current.delete(edition.id);
                  }}
                  type="button"
                  className="site-edition-choice"
                  role="radio"
                  aria-checked={selected}
                  tabIndex={selectedPrimaryId === null
                    ? (edition.id === primaryEditions[0]?.id ? 0 : -1)
                    : (selected ? 0 : -1)}
                  onClick={() => setSelectedId(edition.id)}
                  onKeyDown={(event) => moveSelection(event, edition.id)}
                >
                  <span className="site-edition-card-heading">
                    <strong>{editionCopy.title}</strong>
                    {edition.id === "sim" ? <em>{copy.recommended}</em> : null}
                  </span>
                  <span className="site-edition-audience">{editionCopy.audience}</span>
                  <span className="site-edition-capabilities">
                    {editionCopy.capabilities.map((capability) => (
                      <span key={capability}>{capability}</span>
                    ))}
                  </span>
                </button>
                {ready && selected ? (
                  <a
                    className="site-edition-action"
                    href={edition.downloadUrl ?? undefined}
                    download={edition.fileName}
                  >
                    <DownloadIcon />
                    {copy.confirm}
                  </a>
                ) : (
                  <button
                    type="button"
                    className="site-edition-action"
                    disabled={!ready}
                    onClick={() => setSelectedId(edition.id)}
                  >
                    {ready ? copy.select : copy.soon}
                  </button>
                )}
              </article>
            );
          })}
        </div>

        {universalEdition ? (
          <div
            className="site-edition-universal"
            data-ready={isEditionDownloadReady(universalEdition) || undefined}
            data-selected={selectedId === universalEdition.id || undefined}
          >
            <span>{copy.universal}</span>
            {isEditionDownloadReady(universalEdition) && selectedId === universalEdition.id ? (
              <a
                href={universalEdition.downloadUrl ?? undefined}
                download={universalEdition.fileName}
              >
                <DownloadIcon />
                {copy.confirm}
              </a>
            ) : (
              <button
                type="button"
                disabled={!isEditionDownloadReady(universalEdition)}
                onClick={() => setSelectedId(universalEdition.id)}
              >
                {isEditionDownloadReady(universalEdition) ? copy.chooseUniversal : copy.soon}
              </button>
            )}
          </div>
        ) : null}

        <p className="site-edition-pack-note">{copy.vehiclePacks}</p>

        <div className="site-edition-current">
          <div>
            <strong>{copy.currentTitle}</strong>
            <span>{copy.currentBody}</span>
          </div>
          <a
            href={currentRelease.downloadUrl}
            download={currentRelease.fileName}
          >
            <DownloadIcon />
            {copy.currentAction}
          </a>
        </div>
      </section>
    </div>
  );
}
