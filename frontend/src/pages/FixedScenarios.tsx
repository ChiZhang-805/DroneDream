import { ArrowRight, ChevronLeft, ChevronRight, Gauge, Wind } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { recordProductEvent } from "../features/analytics/productEvents";
import { ExperienceTrackPreview } from "../features/experiment/ExperienceTrackPreview";
import {
  STARTER_EXPERIENCE_TEMPLATES,
  type StarterExperienceId,
} from "../features/experiment/experienceTemplates";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";
import { generateReferenceTrack } from "../utils/referenceTrack";

type ScenarioDifficulty = "simple" | "medium";

interface FixedScenarioDefinition {
  id: StarterExperienceId;
  difficulty: ScenarioDifficulty;
  titleKey: TranslationKey;
}

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
  {
    id: "precision-hover",
    difficulty: "simple",
    titleKey: "scenarioLibrary.precisionHover.title",
  },
  {
    id: "compact-circle",
    difficulty: "simple",
    titleKey: "scenarioLibrary.compactCircle.title",
  },
  {
    id: "gust-recovery-circle",
    difficulty: "medium",
    titleKey: "scenarioLibrary.gustRecovery.title",
  },
  {
    id: "crosswind-figure-eight",
    difficulty: "medium",
    titleKey: "scenarioLibrary.figureEight.title",
  },
]);

const SCENARIOS_PER_PAGE = 4;

function scenarioPreviewPoints(id: StarterExperienceId) {
  const template = STARTER_EXPERIENCE_TEMPLATES.find((candidate) => candidate.id === id);
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

  const changePage = (direction: -1 | 1) => {
    setPageIndex((current) => (current + direction + pageCount) % pageCount);
  };

  return (
    <div className="fixed-scenarios-page">
      <header className="page-header fixed-scenarios-header">
        <h1>{t("scenarioLibrary.title")}</h1>
        <div
          className="fixed-scenarios-pagination"
          role="group"
          aria-label={t("scenarioLibrary.pagination.label")}
        >
          <button
            type="button"
            onClick={() => changePage(-1)}
            aria-label={t("scenarioLibrary.pagination.previous")}
          >
            <ChevronLeft aria-hidden="true" />
          </button>
          <span aria-live="polite">
            {t("scenarioLibrary.pagination.status", {
              current: pageIndex + 1,
              total: pageCount,
            })}
          </span>
          <button
            type="button"
            onClick={() => changePage(1)}
            aria-label={t("scenarioLibrary.pagination.next")}
          >
            <ChevronRight aria-hidden="true" />
          </button>
        </div>
      </header>

      <div className="fixed-scenarios-grid">
        {visibleDefinitions.map((definition) => {
          const template = STARTER_EXPERIENCE_TEMPLATES.find(
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
                <h2>{t(definition.titleKey)}</h2>
                <span className="fixed-scenario-difficulty">
                  {definition.difficulty === "simple"
                    ? <Gauge aria-hidden="true" />
                    : <Wind aria-hidden="true" />}
                  {t(difficultyKey)}
                </span>
              </div>
              <dl className="fixed-scenario-facts">
                <div>
                  <dt>{t("scenarioLibrary.track")}</dt>
                  <dd>{template.patch.track_type === "hover"
                    ? t("scenarioLibrary.track.hover")
                    : template.patch.track_type === "circle"
                      ? t("scenarioLibrary.track.circle", {
                        radius: template.patch.circle_radius_m,
                      })
                      : t("scenarioLibrary.track.figureEight")}</dd>
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
                compact
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
