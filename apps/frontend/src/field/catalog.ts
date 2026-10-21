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
    fieldManifestSha256: "82b3f6edade30bf88e778c1e65f86ad7bf30bc998b5a4afe732897eaba603d0a",
    vehiclePackRegistrySha256: "569a691bd1e6a074f4fc3d37f1a6f59f86c090295394941f99f6abd4056687f0",
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
      manifestSha256: "30b275c651089106443aeadf5477beb358c81cdc2c1369b53c03d5d42294eefd",
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
      manifestSha256: "cd68561d99b84f46f6650e770e13ecc43019aba5760896740fd239989ef144c0",
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
      manifestSha256: "0ce165af8c6c3e6a0498f2189f772b769d98a1aa27e71b98c6c6c91b01bf450c",
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
      manifestSha256: "1092abff8df727562eafa502587d24e40b9839d4e8e279a4ed36865377066b8c",
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
      manifestSha256: "c10b4be345b266b484896e520a83fd37384ba2545c293b87da318f9da2861325",
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
      manifestSha256: "81f68008e93e562088d13d497d2ced20e29705cb8a293a5ef5a6271e4c749bfc",
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
