allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)

    project.afterEvaluate {
        if (project.plugins.hasPlugin("com.android.application") ||
            project.plugins.hasPlugin("com.android.library")) {
            val android = project.extensions.getByName("android")
                as com.android.build.gradle.BaseExtension
            android.compileSdkVersion(36)
            // Inject namespace for plugins that only declare it in AndroidManifest
            if (project.plugins.hasPlugin("com.android.library")) {
                if (android.namespace.isNullOrEmpty()) {
                    val manifest = project.file("src/main/AndroidManifest.xml")
                    if (manifest.exists()) {
                        val pkg = Regex("""package="([^"]+)"""")
                            .find(manifest.readText())?.groupValues?.get(1)
                        if (!pkg.isNullOrEmpty()) {
                            android.namespace = pkg
                        }
                    }
                }
                // Override CMake version to match what's installed in the SDK
                val enb = android.externalNativeBuild
                val cmakeExt = enb.cmake
                if (cmakeExt.path != null) {
                    cmakeExt.version = "3.22.1"
                }
            }
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
