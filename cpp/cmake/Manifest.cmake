file(SHA256 "${PLUGIN}" binary_sha)
file(SHA256 "${SDK}/CLOAPIInterface/CLOAPIInterface.h" header_sha)
file(WRITE "${PLUGIN}.json" "{\n  \"backend\": \"cpp\",\n  \"protocol\": 3,\n  \"plugin_abi\": 1,\n  \"target_clo_sdk\": \"2026.1.224\",\n  \"qt\": \"${QT}\",\n  \"configuration\": \"${CONFIG}\",\n  \"compiler\": \"${COMPILER}\",\n  \"binary_sha256\": \"${binary_sha}\",\n  \"sdk_interface_header_sha256\": \"${header_sha}\"\n}\n")
