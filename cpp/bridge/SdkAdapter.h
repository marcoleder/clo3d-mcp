#pragma once
#include "include/CloApiData.h"
#include <functional>
#include <map>
#include <string>
#include <tuple>
#include <vector>

namespace clo::bridge {
// Only the SDK surface used by the bridge. Production borrows all five CLO
// interfaces; tests inject typed callables without a CLO process or singleton.
struct SdkAdapter {
    using Strings = std::vector<std::string>;
    using StringMap = std::map<std::string, std::string>;
    using Points = std::vector<std::tuple<float, float, int>>;
    using Options = Marvelous::ImportExportOption;
    std::function<bool()> available;
    std::function<std::string()> GetProjectName, GetProjectFilePath, ExportGarmentInformationToStream, GetCustomViewInformation;
    std::function<int()> GetMajorVersion, GetMinorVersion, GetPatchVersion, GetPatternCount, GetAvatarCount;
    std::function<unsigned()> GetColorwayCount, GetCurrentColorwayIndex;
    std::function<void()> NewProject, Refresh3DWindow;
    std::function<bool(const std::string&)> ImportFile;
    std::function<std::string(const std::string&)> ExportZPrj, ExportThumbnail3D;
    std::function<std::string(int)> GetPatternPieceName, GetPatternInformation;
    std::function<StringMap(int)> GetBoundingBoxOfPattern;
    std::function<std::vector<StringMap>()> GetArrangementList;
    std::function<void(int, std::string)> SetPatternPieceName;
    std::function<int(int, float, float)> CopyPatternPieceMove;
    std::function<void(int)> DeletePatternPiece;
    std::function<void(int, bool, bool)> FlipPatternPiece;
    std::function<int(Points)> CreatePatternWithPoints;
    std::function<unsigned(int)> GetFabricCount;
    std::function<std::string(int)> GetFabricName;
    std::function<unsigned(const std::string&)> AddFabric;
    std::function<bool(unsigned, const std::string&)> ReplaceFabric;
    std::function<bool(unsigned)> DeleteFabric;
    std::function<bool(unsigned, unsigned, int)> AssignFabricToPattern;
    std::function<bool(unsigned, unsigned, float, float, float, float)> SetFabricPBRMaterialBaseColor;
    std::function<int(unsigned)> GetFabricIndexForPattern;
    std::function<Strings()> GetColorwayNameList, GetAvatarNameList;
    std::function<std::vector<int>()> GetAvatarGenderList;
    std::function<void(unsigned)> SetCurrentColorwayIndex, DeleteColorwayItem;
    std::function<void(unsigned, const std::string&)> SetColorwayName;
    std::function<std::string(unsigned)> GetColorwayName;
    std::function<unsigned(unsigned, int)> CopyColorway;
    std::function<void(bool)> SetShowHideAvatar;
    std::function<bool(int)> IsShowAvatar;
    std::function<bool(const std::string&, const Options&)> ImportAvatar;
    std::function<bool(const std::string&, const std::string&)> ImportAVAC;
    std::function<bool(unsigned)> Simulate;
    std::function<void(int, int)> SetSimulationQuality;
    std::function<std::pair<int, int>()> GetSimulationQuality;
    std::function<Strings(const std::string&, const Options&)> ExportOBJ, ExportFBX, ExportGLB;
    std::function<Strings(const std::string&, const Options&, bool)> ExportGLTF;
    std::function<std::vector<Strings>(const std::string&)> ExportSnapshot3D;
    std::function<Strings(const std::string&, unsigned, unsigned, unsigned, unsigned)> ExportTurntableImagesByColorwayIndex;
    std::function<void(const std::string&, const Marvelous::ExportTechpackOption&)> ExportTechPack;
};
SdkAdapter hostSdk();
}
