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
    fieldManifestSha256: "130270577240fdd5d79d3a35a71fced7b3472105df97c7bc2323a19184610292",
    vehiclePackRegistrySha256: "7fbe1ec9eb29e3998f48ced5001a34d6423e1de946fb7c5a554a43fed56ee5c7",
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
      manifestSha256: "3fefda5f57f34095b6db979768aced2ba7fb7df8046b1858e8df1ff664225ab3",
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
      manifestSha256: "02ba34bccd6656e6d20e8022a94db1976b9e4a849757e0f9d78927a72883ba0d",
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
      manifestSha256: "3cbd02332027078c8426cd68b3a5f5b24d42165fc15f68aa3f7213d324df46b8",
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
      manifestSha256: "104edd21c05fcd1da2a0c253d9bfb7058ad8ab13aafaa7bfb0e7faa0c7d271ef",
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
      manifestSha256: "36e8f51915cc1877e38104f2d8ee8725d4a2ea5688a5d71d9b7ab40abbbe7885",
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
      manifestSha256: "54ce400438520944708899ca71a1608126b96923351c1427ec0773e6f3e8bee2",
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
      manifestSha256: "43a39a061f832b40f39aaf9722e6928f5b685e9b1f68f70e08726f14119191cc",
    },
  ],
};
