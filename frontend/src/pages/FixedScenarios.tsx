import { ArrowRight, ChevronLeft, ChevronRight, Gauge, Wind } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { recordProductEvent } from "../features/analytics/productEvents";
import { ExperienceTrackPreview } from "../features/experiment/ExperienceTrackPreview";
import {
  FIXED_SCENARIO_TEMPLATES,
  type FixedScenarioId,
} from "../features/experiment/experienceTemplates";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";
import { generateReferenceTrack } from "../utils/referenceTrack";

type ScenarioDifficulty = "simple" | "medium";

interface FixedScenarioDefinition {
  id: FixedScenarioId;
  difficulty: ScenarioDifficulty;
  titleKey: TranslationKey;
}

const SCENARIOS_PER_PAGE = 4;

const FIXED_SCENARIO_DEFINITIONS: readonly FixedScenarioDefinition[] = Object.freeze([
  {
    id: "hover-basics",
    difficulty: "simple",
    titleKey: "scenarioLibrary.hover.title",
  },
  {
    id: "first-circle",
    difficulty: "simple",
    titleKey: "scenarioLibrary.circle.title",
  },
  {
    id: "light-wind-circle",
    difficulty: "medium",
    titleKey: "scenarioLibrary.wind.title",
  },
  {
    id: "wind-sensor-circle",
    difficulty: "medium",
    titleKey: "scenarioLibrary.combined.title",
  },
  { id: "wide-circle", difficulty: "simple", titleKey: "scenarioLibrary.wideCircle.title" },
  { id: "tight-circle", difficulty: "medium", titleKey: "scenarioLibrary.tightCircle.title" },
  { id: "figure-eight", difficulty: "medium", titleKey: "scenarioLibrary.figureEight.title" },
  { id: "u-turn", difficulty: "medium", titleKey: "scenarioLibrary.uTurn.title" },
  { id: "steady-crosswind", difficulty: "medium", titleKey: "scenarioLibrary.steadyCrosswind.title" },
  { id: "gust-circle", difficulty: "medium", titleKey: "scenarioLibrary.gustCircle.title" },
  { id: "windy-figure-eight", difficulty: "medium", titleKey: "scenarioLibrary.windyFigureEight.title" },
  { id: "recovery-u-turn", difficulty: "medium", titleKey: "scenarioLibrary.recoveryUTurn.title" },
  { id: "gps-noise-circle", difficulty: "medium", titleKey: "scenarioLibrary.gpsNoiseCircle.title" },
  { id: "baro-noise-hover", difficulty: "medium", titleKey: "scenarioLibrary.baroNoiseHover.title" },
  { id: "imu-noise-figure-eight", difficulty: "medium", titleKey: "scenarioLibrary.imuNoiseFigureEight.title" },
  { id: "dropout-circle", difficulty: "medium", titleKey: "scenarioLibrary.dropoutCircle.title" },
  { id: "payload-hover", difficulty: "medium", titleKey: "scenarioLibrary.payloadHover.title" },
  { id: "payload-circle", difficulty: "medium", titleKey: "scenarioLibrary.payloadCircle.title" },
  { id: "voltage-sag-circle", difficulty: "medium", titleKey: "scenarioLibrary.voltageSagCircle.title" },
  { id: "low-battery-u-turn", difficulty: "medium", titleKey: "scenarioLibrary.lowBatteryUTurn.title" },
  { id: "holdout-circle", difficulty: "medium", titleKey: "scenarioLibrary.holdoutCircle.title" },
  { id: "robust-figure-eight", difficulty: "medium", titleKey: "scenarioLibrary.robustFigureEight.title" },
  { id: "qualification-u-turn", difficulty: "medium", titleKey: "scenarioLibrary.qualificationUTurn.title" },
  { id: "combined-qualification", difficulty: "medium", titleKey: "scenarioLibrary.combinedQualification.title" },
]);

function scenarioPreviewPoints(id: FixedScenarioId) {
  const template = FIXED_SCENARIO_TEMPLATES.find((candidate) => candidate.id === id);
  if (!template || template.patch.track_type === "custom") return [];
  return generateReferenceTrack(
    template.patch.track_type,
    Number(template.patch.start_x),
    Number(template.patch.start_y),
    Number(template.patch.altitude_m),
    {
      circle_radius_m: Number(template.patch.circle_radius_m),
      u_turn_straight_length_m: 10,
      u_turn_turn_radius_m: 3,
      lemniscate_scale_m: 4,
    },
  );
}

export function FixedScenarios() {
  const { t } = useI18n();
  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.ceil(FIXED_SCENARIO_DEFINITIONS.length / SCENARIOS_PER_PAGE);
  const visibleDefinitions = FIXED_SCENARIO_DEFINITIONS.slice(
    pageIndex * SCENARIOS_PER_PAGE,
    (pageIndex + 1) * SCENARIOS_PER_PAGE,
  );

  return (
    <div className="fixed-scenarios-page">
      <header className="page-header fixed-scenarios-header">
        <h1>{t("scenarioLibrary.title")}</h1>
        <div className="fixed-scenarios-pagination" role="group" aria-label={t("scenarioLibrary.paginationLabel")}>
          <button
            type="button"
            onClick={() => setPageIndex((current) => Math.max(0, current - 1))}
            disabled={pageIndex === 0}
            aria-label={t("scenarioLibrary.previousPage")}
          >
            <ChevronLeft aria-hidden="true" />
          </button>
          <span aria-live="polite">{pageIndex + 1} / {pageCount}</span>
          <button
            type="button"
            onClick={() => setPageIndex((current) => Math.min(pageCount - 1, current + 1))}
            disabled={pageIndex === pageCount - 1}
            aria-label={t("scenarioLibrary.nextPage")}
          >
            <ChevronRight aria-hidden="true" />
          </button>
        </div>
      </header>
      <p className="sr-only">{t("scenarioLibrary.safeHandoff")}</p>

      <div className="fixed-scenarios-grid">
        {visibleDefinitions.map((definition) => {
          const template = FIXED_SCENARIO_TEMPLATES.find(
            (candidate) => candidate.id === definition.id,
          );
          if (!template) return null;
          const points = scenarioPreviewPoints(definition.id);
          const difficultyKey = definition.difficulty === "simple"
            ? "scenarioLibrary.difficulty.simple"
            : "scenarioLibrary.difficulty.medium";
          const isWindy = Number(template.patch.wind_north) > 0
            || Number(template.patch.wind_east) > 0
            || Number(template.patch.wind_south) > 0
            || Number(template.patch.wind_west) > 0;
          const hasSensorNoise = template.patch.noise_search_enabled;

          return (
            <article
              key={template.key}
              className={`fixed-scenario-card fixed-scenario-${definition.difficulty}`}
              data-template-key={template.key}
            >
              <div className="fixed-scenario-card-heading">
                <div>
                  <span className="fixed-scenario-difficulty">
                    {definition.difficulty === "simple"
                      ? <Gauge aria-hidden="true" />
                      : <Wind aria-hidden="true" />}
                    {t(difficultyKey)}
                  </span>
                  <h2>{t(definition.titleKey)}</h2>
                </div>
                <code>{template.key}</code>
              </div>
              <dl className="fixed-scenario-facts">
                <div>
                  <dt>{t("scenarioLibrary.track")}</dt>
                  <dd>{template.patch.track_type === "hover"
                    ? t("scenarioLibrary.track.hover")
                    : template.patch.track_type === "u_turn"
                      ? t("scenarioLibrary.track.uTurn")
                      : template.patch.track_type === "lemniscate"
                        ? t("scenarioLibrary.track.figureEight")
                        : t("scenarioLibrary.track.circle")}</dd>
                </div>
                <div>
                  <dt>{t("scenarioLibrary.altitude")}</dt>
                  <dd>{template.patch.altitude_m} m</dd>
                </div>
                <div>
                  <dt>{t("scenarioLibrary.disturbance")}</dt>
                  <dd>{isWindy && hasSensorNoise
                    ? t("scenarioLibrary.disturbance.windAndNoise", {
                      speed: Math.max(
                        Number(template.patch.wind_north),
                        Number(template.patch.wind_east),
                        Number(template.patch.wind_south),
                        Number(template.patch.wind_west),
                      ),
                    })
                    : isWindy
                      ? t("scenarioLibrary.disturbance.wind", {
                        speed: Math.max(
                          Number(template.patch.wind_north),
                          Number(template.patch.wind_east),
                          Number(template.patch.wind_south),
                          Number(template.patch.wind_west),
                        ),
                      })
                    : t("scenarioLibrary.disturbance.calm")}</dd>
                </div>
                <div>
                  <dt>{t("scenarioLibrary.simulator")}</dt>
                  <dd>{t("scenarioLibrary.simulator.px4")}</dd>
                </div>
              </dl>
              <ExperienceTrackPreview
                trackType={template.patch.track_type}
                points={points}
                altitudeM={Number(template.patch.altitude_m)}
                title={t("scenarioLibrary.preview")}
                hoverLabel={t("wizard.preview.hover")}
                routeLabel={t("wizard.preview.route")}
                pointCountLabel={t("wizard.preview.pointCount", { count: points.length })}
                localOnlyLabel={t("scenarioLibrary.localPreview")}
              />
              <Link
                className="btn btn-primary fixed-scenario-use"
                to={`/jobs/new?scenario=${encodeURIComponent(template.key)}`}
                onClick={() => {
                  void recordProductEvent("fixed_scenario_selected", {
                    template_key: template.key,
                    difficulty: definition.difficulty,
                  });
                }}
              >
                {t("scenarioLibrary.use")}
                <ArrowRight aria-hidden="true" />
              </Link>
            </article>
          );
        })}
      </div>
    </div>
  );
}
