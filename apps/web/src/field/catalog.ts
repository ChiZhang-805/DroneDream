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
    fieldManifestSha256: "15183d231ed96a825c38e3804f4c3d48bbc7b3596fdb94ad234d5a746cc08cd4",
    vehiclePackRegistrySha256: "feb5470690bd1e75d1be341c0dec6a6bae8d62106f3fae78181438974813cad0",
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
      manifestSha256: "9dec4d5a041482fa69f2ccb270afb0402e3726c3b8e727f16692842b2c240f6e",
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
      manifestSha256: "4771dd061cde8988610966f3484d16deb0dbfe209ab86a485201e5c3e899a069",
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
      manifestSha256: "e81312ee2eda1aa8c2a84dfc8a30e42b1e9debabc4b654f73e30efafa209769b",
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
      manifestSha256: "a5fd1f40b08ab8bc29adb4ab5206e52f14a5251a70bb7458f8614bade4459ff4",
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
      manifestSha256: "b0c5b8f51ca6b6cb2ed226174295a401209d448c40c5e511988b81f26d63d6d1",
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
      manifestSha256: "2c2bf062f29b606ff5d8a29807514ebeed2020de46356e10164d769721514528",
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
      manifestSha256: "8b9f8f35cc2d0ac15e29fda861286df030f451d5bfc29f1c739f3cd9a3ee7994",
    },
  ],
};
