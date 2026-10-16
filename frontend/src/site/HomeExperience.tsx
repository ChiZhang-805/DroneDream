import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type WheelEvent,
} from "react";

import type { WebsiteRelease } from "./release";

import heroCampus from "./assets/home/hero-campus.webp";
import bridgeInspection from "./assets/home/card-bridge-inspection.webp";
import buildingInspection from "./assets/home/card-building-inspection.webp";
import campusDelivery from "./assets/home/card-campus-delivery.webp";
import coastalWindTest from "./assets/home/card-coastal-wind-test.webp";
import constructionProgress from "./assets/home/card-construction-progress.webp";
import emergencySearch from "./assets/home/card-emergency-search.webp";
import forestMapping from "./assets/home/card-forest-mapping.webp";
import industrialMapping from "./assets/home/card-industrial-mapping.webp";
import nightPatrol from "./assets/home/card-night-patrol.webp";
import solarSurvey from "./assets/home/card-solar-survey.webp";
import warehouseInventory from "./assets/home/card-warehouse-inventory.webp";

const missionCards = [
  { title: "Campus delivery", image: campusDelivery },
  { title: "Building inspection", image: buildingInspection },
  { title: "Solar array survey", image: solarSurvey },
  { title: "Industrial mapping", image: industrialMapping },
  { title: "Bridge inspection", image: bridgeInspection },
  { title: "Forest mapping", image: forestMapping },
  { title: "Warehouse inventory", image: warehouseInventory },
  { title: "Construction progress", image: constructionProgress },
  { title: "Emergency search", image: emergencySearch },
  { title: "Night corridor patrol", image: nightPatrol },
  { title: "Coastal wind test", image: coastalWindTest },
] as const;

const initialCard = 0;

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v11m0 0 4-4m-4 4-4-4M4 17v2.5h16V17" />
    </svg>
  );
}

export function HomeExperience({ release }: { release: WebsiteRelease }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const [activeCard, setActiveCard] = useState(initialCard);

  const centerCard = useCallback((index: number, behavior: ScrollBehavior) => {
    const viewport = viewportRef.current;
    const card = viewport?.querySelector<HTMLElement>(`[data-home-card-index="${index}"]`);
    if (!viewport || !card) return;
    const viewportBox = viewport.getBoundingClientRect();
    const cardBox = card.getBoundingClientRect();
    const left = viewport.scrollLeft
      + cardBox.left
      - viewportBox.left
      - ((viewport.clientWidth - cardBox.width) / 2);
    if (typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ left, behavior });
    } else {
      viewport.scrollLeft = left;
    }
    setActiveCard(index);
  }, []);

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
  }, []);

  const updateActiveCard = () => {
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const viewport = viewportRef.current;
      if (!viewport) return;
      const viewportBox = viewport.getBoundingClientRect();
      const center = viewportBox.left + (viewportBox.width / 2);
      const cards = Array.from(
        viewport.querySelectorAll<HTMLElement>("[data-home-card-index]"),
      );
      let nearestIndex = activeCard;
      let nearestDistance = Number.POSITIVE_INFINITY;
      cards.forEach((card) => {
        const index = Number(card.dataset.homeCardIndex);
        const cardBox = card.getBoundingClientRect();
        const distance = Math.abs((cardBox.left + (cardBox.width / 2)) - center);
        if (distance < nearestDistance) {
          nearestIndex = index;
          nearestDistance = distance;
        }
      });
      setActiveCard(nearestIndex);
    });
  };

  const moveCard = (direction: -1 | 1) => {
    const next = Math.min(missionCards.length - 1, Math.max(0, activeCard + direction));
    centerCard(next, "smooth");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    moveCard(event.key === "ArrowLeft" ? -1 : 1);
  };

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const delta = Math.abs(event.deltaY) > Math.abs(event.deltaX)
      ? event.deltaY
      : event.deltaX;
    if (delta === 0) return;
    event.preventDefault();
    viewport.scrollLeft += delta * 0.72;
  };

  return (
    <section
      className="site-home-experience"
      id="home"
      aria-labelledby="home-experience-title"
      style={{ "--home-hero-image": `url(${heroCampus})` } as CSSProperties}
    >
      <div className="site-home-backdrop" aria-hidden="true" />
      <div className="site-home-copy">
        <h1 id="home-experience-title">Describe the mission. Watch it fly.</h1>
        <p>
          Natural-language missions, planned and simulated in one workspace.<br />{" "}
          From map-aware routing to live flight views.
        </p>
        <a
          className="site-home-download"
          href={release.downloadUrl}
          download={release.fileName}
        >
          <DownloadIcon />
          <span>Download Universal</span>
        </a>
      </div>

      <div className="site-home-card-stage" aria-label="DroneDream mission gallery">
        <div
          ref={viewportRef}
          className="site-home-card-viewport"
          role="region"
          aria-roledescription="carousel"
          aria-label="Mission examples"
          tabIndex={0}
          onKeyDown={handleKeyDown}
          onScroll={updateActiveCard}
          onWheel={handleWheel}
        >
          <div className="site-home-card-track">
            {missionCards.map((card, index) => {
              const distance = Math.abs(index - activeCard);
              const style = {
                "--card-scale": Math.max(0.935, 1.025 - (distance * 0.018)),
                "--card-lift": `${Math.max(0, 12 - (distance * 3))}px`,
                "--card-brightness": Math.max(0.56, 1 - (distance * 0.1)),
                zIndex: missionCards.length - distance,
              } as CSSProperties;
              return (
                <button
                  key={card.title}
                  type="button"
                  className={`site-home-card${index === activeCard ? " is-active" : ""}`}
                  data-home-card-index={index}
                  aria-label={`${card.title}, card ${index + 1} of ${missionCards.length}`}
                  aria-current={index === activeCard ? "true" : undefined}
                  style={style}
                  onClick={() => centerCard(index, "smooth")}
                >
                  <img src={card.image} alt="" draggable="false" />
                  <span>{card.title}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="site-home-card-position" aria-live="polite">
          <span>{String(activeCard + 1).padStart(2, "0")}</span>
          <i aria-hidden="true" />
          <span>{String(missionCards.length).padStart(2, "0")}</span>
        </div>
      </div>
    </section>
  );
}
