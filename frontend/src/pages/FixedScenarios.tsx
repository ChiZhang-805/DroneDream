import { ArrowRight, Gauge, ShieldCheck, Wind } from "lucide-react";
import { Link } from "react-router-dom";

import { ExperienceTrackPreview } from "../features/experiment/ExperienceTrackPreview";
import {
  STARTER_EXPERIENCE_CATALOG_VERSION,
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
  descriptionKey: TranslationKey;
  goalKey: TranslationKey;
}

const FIXED_SCENARIO_DEFINITIONS: readonly FixedScenarioDefinition[] = Object.freeze([
  {
    id: "hover-basics",
    difficulty: "simple",
    titleKey: "scenarioLibrary.hover.title",
    descriptionKey: "scenarioLibrary.hover.description",
    goalKey: "scenarioLibrary.hover.goal",
  },
  {
    id: "first-circle",
    difficulty: "simple",
    titleKey: "scenarioLibrary.circle.title",
    descriptionKey: "scenarioLibrary.circle.description",
    goalKey: "scenarioLibrary.circle.goal",
  },
  {
    id: "light-wind-circle",
    difficulty: "medium",
    titleKey: "scenarioLibrary.wind.title",
    descriptionKey: "scenarioLibrary.wind.description",
    goalKey: "scenarioLibrary.wind.goal",
  },
  {
    id: "wind-sensor-circle",
    difficulty: "medium",
    titleKey: "scenarioLibrary.combined.title",
    descriptionKey: "scenarioLibrary.combined.description",
    goalKey: "scenarioLibrary.combined.goal",
  },
]);

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

  return (
    <div className="fixed-scenarios-page">
      <header className="page-header fixed-scenarios-header">
        <div>
          <div className="page-eyebrow">PX4 / GAZEBO STUDY</div>
          <h1>{t("scenarioLibrary.title")}</h1>
          <p className="page-header-subtitle">{t("scenarioLibrary.subtitle")}</p>
        </div>
        <span className="fixed-scenarios-version">
          {t("scenarioLibrary.catalogVersion", {
            version: STARTER_EXPERIENCE_CATALOG_VERSION,
          })}
        </span>
      </header>

      <div className="fixed-scenarios-assurance" role="note">
        <ShieldCheck aria-hidden="true" />
        <span>{t("scenarioLibrary.safeHandoff")}</span>
      </div>

      <div className="fixed-scenarios-grid">
        {FIXED_SCENARIO_DEFINITIONS.map((definition) => {
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
              <p>{t(definition.descriptionKey)}</p>
              <dl className="fixed-scenario-facts">
                <div>
                  <dt>{t("scenarioLibrary.track")}</dt>
                  <dd>{template.patch.track_type === "hover"
                    ? t("scenarioLibrary.track.hover")
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
              <div className="fixed-scenario-goal">
                <strong>{t("scenarioLibrary.goal")}</strong>
                <span>{t(definition.goalKey)}</span>
              </div>
              <Link
                className="btn btn-primary fixed-scenario-use"
                to={`/jobs/new?scenario=${encodeURIComponent(template.key)}`}
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
