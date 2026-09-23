#include "SdkAdapter.h"
#include "CLOAPIInterface.h"

namespace clo::bridge {
SdkAdapter hostSdk() {
    SdkAdapter sdk;
    sdk.available = [] { return EXPORT_API && IMPORT_API && UTILITY_API && FABRIC_API && PATTERN_API; };
    // Generic lambdas preserve the typed adapter signatures and select SDK
    // overloads at compile time. Pointers are borrowed anew for every call.
#define BIND(api, method) sdk.method = [](auto&&... args) { return api->method(std::forward<decltype(args)>(args)...); }
    BIND(UTILITY_API, GetProjectName);
    BIND(UTILITY_API, GetProjectFilePath);
    BIND(UTILITY_API, GetMajorVersion);
    BIND(UTILITY_API, GetMinorVersion);
    BIND(UTILITY_API, GetPatchVersion);
    BIND(UTILITY_API, GetColorwayCount);
    BIND(UTILITY_API, GetCurrentColorwayIndex);
    BIND(UTILITY_API, NewProject);
    BIND(UTILITY_API, Refresh3DWindow);
    BIND(UTILITY_API, GetCustomViewInformation);
    BIND(UTILITY_API, SetCurrentColorwayIndex);
    BIND(UTILITY_API, SetColorwayName);
    BIND(UTILITY_API, GetColorwayName);
    BIND(UTILITY_API, CopyColorway);
    BIND(UTILITY_API, DeleteColorwayItem);
    BIND(UTILITY_API, SetShowHideAvatar);
    BIND(UTILITY_API, IsShowAvatar);
    BIND(UTILITY_API, Simulate);
    BIND(UTILITY_API, SetSimulationQuality);
    BIND(UTILITY_API, GetSimulationQuality);
    BIND(PATTERN_API, GetPatternCount);
    BIND(PATTERN_API, GetPatternPieceName);
    BIND(PATTERN_API, GetPatternInformation);
    BIND(PATTERN_API, GetBoundingBoxOfPattern);
    BIND(PATTERN_API, GetArrangementList);
    BIND(PATTERN_API, SetPatternPieceName);
    BIND(PATTERN_API, CopyPatternPieceMove);
    BIND(PATTERN_API, DeletePatternPiece);
    BIND(PATTERN_API, FlipPatternPiece);
    BIND(PATTERN_API, CreatePatternWithPoints);
    BIND(FABRIC_API, GetFabricCount);
    BIND(FABRIC_API, GetFabricName);
    BIND(FABRIC_API, AddFabric);
    BIND(FABRIC_API, ReplaceFabric);
    BIND(FABRIC_API, DeleteFabric);
    BIND(FABRIC_API, AssignFabricToPattern);
    BIND(FABRIC_API, SetFabricPBRMaterialBaseColor);
    BIND(FABRIC_API, GetFabricIndexForPattern);
    BIND(EXPORT_API, ExportGarmentInformationToStream);
    BIND(EXPORT_API, ExportZPrj);
    BIND(EXPORT_API, ExportThumbnail3D);
    BIND(EXPORT_API, GetColorwayNameList);
    BIND(EXPORT_API, GetAvatarCount);
    BIND(EXPORT_API, GetAvatarNameList);
    BIND(EXPORT_API, GetAvatarGenderList);
    BIND(EXPORT_API, ExportOBJ);
    BIND(EXPORT_API, ExportFBX);
    BIND(EXPORT_API, ExportGLB);
    BIND(EXPORT_API, ExportGLTF);
    BIND(EXPORT_API, ExportSnapshot3D);
    BIND(EXPORT_API, ExportTurntableImagesByColorwayIndex);
    BIND(EXPORT_API, ExportTechPack);
    BIND(IMPORT_API, ImportFile);
    BIND(IMPORT_API, ImportAvatar);
    BIND(IMPORT_API, ImportAVAC);
#undef BIND
    return sdk;
}
}
