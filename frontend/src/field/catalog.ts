export type FieldLocale = "en" | "zh-CN";
export type FieldValidationStatus = "validated" | "contract-only" | "planned";

export interface FieldCatalogController {
  vendor: string;
  model: string;
  status: FieldValidationStatus;
}

export interface FieldCatalogVehiclePack {
  packId: string;
  displayName: Record<FieldLocale, string>;
  manufacturer: string;
  vehicleClass: string;
  validationStatus: FieldValidationStatus;
  validationTier: string;
  adapterStatus: "integrated-contract" | "contract-only" | "planned";
  controllers: FieldCatalogController[];
  manifestSha256: string;
}

export interface FieldCatalog {
  schemaVersion: 1;
  kind: "dronedream-field-catalog-projection";
  catalogVersion: "1.0.0";
  sourceBindings: {
    fieldManifestSha256: string;
    vehiclePackRegistrySha256: string;
  };
  vehiclePacks: FieldCatalogVehiclePack[];
}

// This edition projection is checked byte-for-byte against the unified catalog
// in fieldCatalog.test.ts. It prevents unrelated edition data entering Field.
export const FIELD_CATALOG: FieldCatalog = {
  schemaVersion: 1,
  kind: "dronedream-field-catalog-projection",
  catalogVersion: "1.0.0",
  sourceBindings: {
    fieldManifestSha256: "638cd447066fad0dfadc1989316531eebfd1c76fa1b2fb123578f54b24f2c962",
    vehiclePackRegistrySha256: "783b29ec866c2a4766ee10aa6257dae8f41bd4eea2de7c9a736279ea14f2fe4a",
  },
  vehiclePacks: [
    {
      packId: "holybro-x500-v2-pixhawk6",
      displayName: {
        en: "Holybro X500 v2 with Pixhawk 6",
        "zh-CN": "Holybro X500 v2 + Pixhawk 6",
      },
      manufacturer: "Holybro",
      vehicleClass: "multicopter-research",
      validationStatus: "contract-only",
      validationTier: "contract-only",
      adapterStatus: "integrated-contract",
      controllers: [
        { vendor: "Holybro", model: "Pixhawk 6C", status: "contract-only" },
        { vendor: "Holybro", model: "Pixhawk 6X", status: "contract-only" },
      ],
      manifestSha256: "999bfa256b0fa1faf04366bbc2dea003b919878aa85be9a1a88ad503dae5d5d5",
    },
    {
      packId: "holybro-s500-v2-pixhawk6c",
      displayName: {
        en: "Holybro S500 v2 with Pixhawk 6C",
        "zh-CN": "Holybro S500 v2 + Pixhawk 6C",
      },
      manufacturer: "Holybro",
      vehicleClass: "multicopter-medium",
      validationStatus: "contract-only",
      validationTier: "contract-only",
      adapterStatus: "integrated-contract",
      controllers: [
        { vendor: "Holybro", model: "Pixhawk 6C", status: "contract-only" },
      ],
      manifestSha256: "8fa0b842329a5b661e2aa9ca5883fdb09ca61154ad232c31f1a430ef05204fd8",
    },
    {
      packId: "holybro-qav250-pixhawk6c-mini",
      displayName: {
        en: "Holybro QAV250 with Pixhawk 6C Mini",
        "zh-CN": "Holybro QAV250 + Pixhawk 6C Mini",
      },
      manufacturer: "Holybro",
      vehicleClass: "multicopter-small",
      validationStatus: "contract-only",
      validationTier: "contract-only",
      adapterStatus: "integrated-contract",
      controllers: [
        { vendor: "Holybro", model: "Pixhawk 6C Mini", status: "contract-only" },
      ],
      manifestSha256: "20ee57a666d5e90c267a86615d7d5e9caeed7395716ecff737212262f510b702",
    },
    {
      packId: "holybro-x650-pixhawk6",
      displayName: {
        en: "Holybro X650 with Pixhawk 6",
        "zh-CN": "Holybro X650 + Pixhawk 6",
      },
      manufacturer: "Holybro",
      vehicleClass: "multicopter-research",
      validationStatus: "contract-only",
      validationTier: "contract-only",
      adapterStatus: "integrated-contract",
      controllers: [
        { vendor: "Holybro", model: "Pixhawk 6C", status: "contract-only" },
        { vendor: "Holybro", model: "Pixhawk 6X", status: "contract-only" },
      ],
      manifestSha256: "ee74d88b4743e29f834db8f19bff6a484c44520d32429efddf071bc7261d722b",
    },
    {
      packId: "amovlab-p450-px4",
      displayName: {
        en: "Amovlab P450 PX4 Research Platform",
        "zh-CN": "阿木实验室 P450 PX4 科研平台",
      },
      manufacturer: "Amovlab",
      vehicleClass: "multicopter-research",
      validationStatus: "planned",
      validationTier: "planned",
      adapterStatus: "planned",
      controllers: [
        { vendor: "Amovlab", model: "Allspark V6C", status: "planned" },
      ],
      manifestSha256: "0cec7c1296cbb198bbd08f2b7b2efe02fe51524dbb1ce4714f802fba2ce4af58",
    },
    {
      packId: "amovlab-mfp450-pixhawk6c",
      displayName: {
        en: "Amovlab MFP450 with Pixhawk 6C",
        "zh-CN": "阿木实验室 MFP450 + Pixhawk 6C",
      },
      manufacturer: "Amovlab",
      vehicleClass: "multicopter-medium",
      validationStatus: "planned",
      validationTier: "planned",
      adapterStatus: "planned",
      controllers: [
        { vendor: "Holybro", model: "Pixhawk 6C", status: "planned" },
        { vendor: "Amovlab", model: "ICF5", status: "planned" },
      ],
      manifestSha256: "0d28a6102bc33250104c8eb8bc9f6e24c3a70d41428444b1b04b2497ba669267",
    },
    {
      packId: "bitcraze-crazyflie-2-1-plus",
      displayName: {
        en: "Bitcraze Crazyflie 2.1+",
        "zh-CN": "Bitcraze Crazyflie 2.1+ 教学微型机",
      },
      manufacturer: "Bitcraze",
      vehicleClass: "multicopter-small",
      validationStatus: "planned",
      validationTier: "planned",
      adapterStatus: "planned",
      controllers: [
        { vendor: "Bitcraze", model: "Crazyflie 2.1+", status: "planned" },
      ],
      manifestSha256: "8ecda457a7dfdcfc2b5d568df5ff17414ad9e039e3f56e89fe164c4519780ad8",
    },
  ],
};
