import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type WheelEvent,
} from "react";

import type { WebsiteRelease } from "./release";

import heroCampus from "./assets/home/hero-campus.webp";
import bridgeInspection from "./assets/home/card-bridge-inspection.webp";
import campusDelivery from "./assets/home/card-campus-delivery.webp";
import coastalWindTest from "./assets/home/card-coastal-wind-test.webp";
import constructionProgress from "./assets/home/card-construction-progress.webp";
import emergencySearch from "./assets/home/card-emergency-search.webp";
import forestMapping from "./assets/home/card-forest-mapping.webp";
import hospitalLogistics from "./assets/home/card-hospital-logistics.webp";
import industrialMapping from "./assets/home/card-industrial-mapping.webp";
import nightPatrol from "./assets/home/card-night-patrol.webp";
import solarSurvey from "./assets/home/card-solar-survey.webp";
import warehouseInventory from "./assets/home/card-warehouse-inventory.webp";

const missionCards = [
  { title: "Campus delivery", image: campusDelivery },
  { title: "Hospital logistics", image: hospitalLogistics },
  { title: "Solar array survey", image: solarSurvey },
  { title: "Industrial plant mapping", image: industrialMapping },
  { title: "Bridge inspection", image: bridgeInspection },
  { title: "Forest conservation", image: forestMapping },
  { title: "Warehouse inventory", image: warehouseInventory },
  { title: "Construction progress", image: constructionProgress },
  { title: "Emergency search", image: emergencySearch },
  { title: "Night corridor patrol", image: nightPatrol },
  { title: "Coastal wind test", image: coastalWindTest },
] as const;

const initialCard = 5;
const loopCopies = [0, 1, 2] as const;

function getCenteredScrollLeft(viewport: HTMLElement, card: HTMLElement) {
  return card.offsetLeft - ((viewport.clientWidth - card.offsetWidth) / 2);
}

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
  const activeCardRef = useRef(initialCard);
  const wheelAccumulatorRef = useRef(0);
  const [activeCard, setActiveCard] = useState(initialCard);

  const centerCard = useCallback((
    index: number,
    behavior: ScrollBehavior,
    direction: -1 | 0 | 1 = 0,
    requestedCopy?: number,
  ) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const selector = requestedCopy === undefined
      ? `[data-home-card-index="${index}"]`
      : `[data-home-card-index="${index}"][data-home-card-copy="${requestedCopy}"]`;
    const candidates = Array.from(viewport.querySelectorAll<HTMLElement>(selector))
      .map((card) => ({ card, left: getCenteredScrollLeft(viewport, card) }));
    if (candidates.length === 0) return;

    const currentLeft = viewport.scrollLeft;
    const directional = direction === 0
      ? candidates
      : candidates.filter(({ left }) => direction > 0
        ? left > currentLeft + 1
        : left < currentLeft - 1);
    const pool = directional.length > 0 ? directional : candidates;
    const target = pool.reduce((nearest, candidate) => {
      const nearestDistance = Math.abs(nearest.left - currentLeft);
      const candidateDistance = Math.abs(candidate.left - currentLeft);
      return candidateDistance < nearestDistance ? candidate : nearest;
    });

    if (typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ left: target.left, behavior });
    } else {
      viewport.scrollLeft = target.left;
    }
    activeCardRef.current = index;
    setActiveCard(index);
  }, []);

  useLayoutEffect(() => {
    centerCard(initialCard, "auto", 0, 1);
  }, [centerCard]);

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
  }, []);

  const normalizeLoopPosition = useCallback((viewport: HTMLDivElement) => {
    const firstPrevious = viewport.querySelector<HTMLElement>(
      '[data-home-card-copy="0"][data-home-card-index="0"]',
    );
    const firstMiddle = viewport.querySelector<HTMLElement>(
      '[data-home-card-copy="1"][data-home-card-index="0"]',
    );
    const secondMiddle = viewport.querySelector<HTMLElement>(
      '[data-home-card-copy="1"][data-home-card-index="1"]',
    );
    const lastMiddle = viewport.querySelector<HTMLElement>(
      `[data-home-card-copy="1"][data-home-card-index="${missionCards.length - 1}"]`,
    );
    if (!firstPrevious || !firstMiddle || !lastMiddle) return;

    const previousStart = getCenteredScrollLeft(viewport, firstPrevious);
    const middleStart = getCenteredScrollLeft(viewport, firstMiddle);
    const middleEnd = getCenteredScrollLeft(viewport, lastMiddle);
    const cycleWidth = middleStart - previousStart;
    if (cycleWidth <= 0) return;

    const cardStep = secondMiddle
      ? Math.abs(getCenteredScrollLeft(viewport, secondMiddle) - middleStart)
      : cycleWidth / missionCards.length;
    const lowerBoundary = middleStart - (cardStep * 0.55);
    const upperBoundary = middleEnd + (cardStep * 0.55);
    let normalizedLeft = viewport.scrollLeft;
    while (normalizedLeft < lowerBoundary) normalizedLeft += cycleWidth;
    while (normalizedLeft > upperBoundary) normalizedLeft -= cycleWidth;
    if (Math.abs(normalizedLeft - viewport.scrollLeft) > 0.5) {
      viewport.scrollLeft = normalizedLeft;
    }
  }, []);

  const updateActiveCard = () => {
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const viewport = viewportRef.current;
      if (!viewport) return;
      normalizeLoopPosition(viewport);
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
      activeCardRef.current = nearestIndex;
      setActiveCard(nearestIndex);
    });
  };

  const moveCard = (direction: -1 | 1) => {
    const next = (activeCardRef.current + direction + missionCards.length) % missionCards.length;
    centerCard(next, "smooth", direction);
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
    const modeScale = event.deltaMode === 1
      ? 33
      : event.deltaMode === 2
        ? viewport.clientWidth
        : 1;
    wheelAccumulatorRef.current += delta * modeScale;
    const stepThreshold = 100;
    const steps = Math.trunc(Math.abs(wheelAccumulatorRef.current) / stepThreshold);
    if (steps === 0) return;
    const direction = wheelAccumulatorRef.current > 0 ? 1 : -1;
    wheelAccumulatorRef.current -= direction * steps * stepThreshold;

    const next = (
      activeCardRef.current
      + (direction * steps)
      + (missionCards.length * steps)
    ) % missionCards.length;
    centerCard(next, "auto", direction);
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
        <h1 id="home-experience-title">Give Every Mission a Flight Agent.</h1>
        <p>
          Turn everyday language into complete drone missions.<br />{" "}
          Plan the route, choose the aircraft, and follow every move.
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
            {loopCopies.flatMap((copyIndex) => missionCards.map((card, index) => {
              const directDistance = Math.abs(index - activeCard);
              const distance = Math.min(directDistance, missionCards.length - directDistance);
              const style = {
                "--card-scale": 1,
                "--card-lift": "0px",
                "--card-brightness": Math.max(0.46, 1 - (distance * 0.18)),
                zIndex: missionCards.length - distance,
              } as CSSProperties;
              return (
                <button
                  key={`${copyIndex}-${card.title}`}
                  type="button"
                  className={`site-home-card${index === activeCard ? " is-active" : ""}`}
                  data-home-card-index={index}
                  data-home-card-copy={copyIndex}
                  aria-label={copyIndex === 1
                    ? `${card.title}, card ${index + 1} of ${missionCards.length}`
                    : undefined}
                  aria-current={copyIndex === 1 && index === activeCard ? "true" : undefined}
                  aria-hidden={copyIndex === 1 ? undefined : "true"}
                  tabIndex={copyIndex === 1 ? 0 : -1}
                  style={style}
                  onClick={() => centerCard(index, "smooth", 0, copyIndex)}
                >
                  <img src={card.image} alt="" draggable="false" />
                  <span>{card.title}</span>
                </button>
              );
            }))}
          </div>
        </div>
      </div>
    </section>
  );
}
