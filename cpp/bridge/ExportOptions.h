#pragma once
#include "SdkAdapter.h"
#include <QJsonObject>
namespace clo::bridge {
Marvelous::ImportExportOption modelOptions(const QJsonObject& params);
Marvelous::ExportTechpackOption techpackOptions(const QJsonObject& params);
}
