// Export the exact mesh interpretation used by Gazebo, including COLLADA axes.
// Build with: g++ -std=c++17 export-gazebo-mesh.cc -o export-gazebo-mesh
//             $(pkg-config --cflags --libs gz-common5-graphics)
#include <gz/common/MeshManager.hh>
#include <gz/common/Mesh.hh>
#include <gz/common/SubMesh.hh>
#include <gz/common/Material.hh>
#include <iomanip>
#include <iostream>

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  const auto mesh = gz::common::MeshManager::Instance()->Load(argv[1]);
  if (!mesh) return 3;
  std::cout << std::setprecision(17) << "[";
  for (unsigned int n = 0; n < mesh->SubMeshCount(); ++n) {
    const auto part = mesh->SubMeshByIndex(n).lock();
    if (part->SubMeshPrimitiveType() != gz::common::SubMesh::TRIANGLES &&
        part->SubMeshPrimitiveType() != gz::common::SubMesh::LINES) {
      std::cerr << "Unsupported primitive " << part->SubMeshPrimitiveType()
                << " in " << part->Name() << " vertices=" << part->VertexCount()
                << " indices=" << part->IndexCount() << "\n";
      return 4;
    }
    if (n) std::cout << ",";
    std::cout << "{\"name\":" << std::quoted(part->Name())
              << ",\"primitive\":" << part->SubMeshPrimitiveType() << ",\"vertices\":[";
    for (unsigned int i = 0; i < part->VertexCount(); ++i) {
      const auto v = part->Vertex(i);
      if (i) std::cout << ",";
      std::cout << "[" << v.X() << "," << v.Y() << "," << v.Z() << "]";
    }
    std::cout << "],\"indices\":[";
    for (unsigned int i = 0; i < part->IndexCount(); ++i) {
      if (i) std::cout << ",";
      std::cout << part->Index(i);
    }
    std::cout << "],\"normals\":[";
    for (unsigned int i = 0; i < part->NormalCount(); ++i) {
      const auto v = part->Normal(i);
      if (i) std::cout << ",";
      std::cout << "[" << v.X() << "," << v.Y() << "," << v.Z() << "]";
    }
    std::cout << "],\"uv\":[";
    for (unsigned int i = 0; i < part->TexCoordCount(); ++i) {
      const auto v = part->TexCoord(i);
      if (i) std::cout << ",";
      std::cout << "[" << v.X() << "," << v.Y() << "]";
    }
    std::cout << "]";
    if (part->GetMaterialIndex()) {
      const auto mat = mesh->MaterialByIndex(*part->GetMaterialIndex());
      const auto c = mat->Diffuse();
      std::cout << ",\"color\":[" << c.R() << "," << c.G() << "," << c.B()
                << "," << c.A() * (1.0 - mat->Transparency()) << "]"
                << ",\"texture\":" << std::quoted(mat->TextureImage());
    }
    std::cout << "}";
  }
  std::cout << "]\n";
}
