/* *************************************************
 * Copyright 2014 TrilioData, Inc.  All rights reserved.
 * *************************************************/

/*
 * trilio-vix-disk-lib.cpp --
 *
 */

#ifdef _WIN32
#include <windows.h>
#include <tchar.h>
#include <process.h>
#else
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
#include <sys/time.h>
#include <signal.h>
#include <unistd.h>
#endif

#include <time.h>
#include <stdlib.h>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
#include <stdexcept>
#include <fstream>
#include <algorithm>

using namespace std;

typedef int64_t int64;
typedef uint64_t uint64;
typedef bool Bool;

#include "vixDiskLib.h"
#include "vixMntapi.h"

using std::cout;
using std::string;
using std::endl;
using std::vector;
using std::stoul;


#define COMMAND_CREATE          (1 << 0)
#define COMMAND_DUMP            (1 << 1)
#define COMMAND_FILL            (1 << 2)
#define COMMAND_INFO            (1 << 3)
#define COMMAND_REDO            (1 << 4)
#define COMMAND_DUMP_META       (1 << 5)
#define COMMAND_READ_META       (1 << 6)
#define COMMAND_WRITE_META      (1 << 7)
#define COMMAND_MULTITHREAD     (1 << 8)
#define COMMAND_CLONE           (1 << 9)
#define COMMAND_READBENCH       (1 << 10)
#define COMMAND_WRITEBENCH      (1 << 11)
#define COMMAND_CHECKREPAIR     (1 << 12)
#define COMMAND_DOWNLOAD        (1 << 13)
#define COMMAND_UPLOAD          (1 << 14)
#define COMMAND_COMPARE         (1 << 15)
#define COMMAND_COPY         	(1 << 16)
#define COMMAND_ATTACH         	(1 << 17)
#define COMMAND_UPLOADEXTENTS   (1 << 18)
#define COMMAND_DOWNLOADEXTENTS (1 << 19)
#define COMMAND_MOUNT           (1 << 20)
#define COMMAND_UNMOUNT         (1 << 21)
#define	COMMAND_SPACE_FOR_CLONE	(1 << 22)

#define VIXDISKLIB_VERSION_MAJOR 5
#define VIXDISKLIB_VERSION_MINOR 5

// Default buffer size (in sectors) for read/write benchmarks
#define DEFAULT_BUFSIZE 128

// Print updated statistics for read/write benchmarks roughly every
// BUFS_PER_STAT sectors (current value is 64MBytes worth of data)
#define BUFS_PER_STAT (128 * 1024)

// buffer size for downloading and uploading data from and to remote disk
#define VIXDISKLIB_BUF_SIZE (128 * VIXDISKLIB_SECTOR_SIZE)

// Per-thread information for multi-threaded VixDiskLib test.
struct ThreadData {
   std::string dstDisk;
   VixDiskLibHandle srcHandle;
   VixDiskLibHandle dstHandle;
   VixDiskLibSectorType numSectors;
};


static struct {
    int command;
    VixDiskLibAdapterType adapterType;
    char *diskPath;
    char *parentPath;
    char *remotePath;
    char *localPath;
    char *extentfile;
    char *mountpointsfile;    
    int  diskonlymount;

    char *transportModes;
    char *metaKey;
    char *metaVal;
    int filler;
    unsigned mbSize;
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibSectorType bufSize;
    uint32 openFlags;
    unsigned numThreads;
    Bool success;
    Bool isRemote;
    char *host;
    char *userName;
    char *password;
    char *thumbPrint;
    int port;
    char *srcPath;
    VixDiskLibConnection connection;
    VixDiskLibConnection localConnection;
    char *vmxSpec;
    bool useInitEx;
    char *cfgFile;
    char *libdir;
    char *ssMoRef;
    int repair;
    char const *source;
    char const *diskType;       
} appGlobals;

static int ParseArguments(int argc, char* argv[]);
static void DoCreate(void);
static void DoRedo(void);
static void DoFill(void);
static void DoDump(void);
static void DoReadMetadata(void);
static void DoWriteMetadata(void);
static void DoDumpMetadata(void);
static void DoInfo(void);
static void DoTestMultiThread(void);
static void DoClone(void);
static int BitCount(int number);
static void DumpBytes(const uint8 *buf, size_t n, int step);
static void DoRWBench(bool read);
static void DoCheckRepair(Bool repair);
static void DoDownload(void);
static void DoUpload(void);
static void DoDownloadExtents(void);
static void DoUploadExtents(void);
static void DoCompare(void);
static void DoCopy(void);
static void DoAttach(void);
static void DoMount(void);
static void DoUnmount(void);
static void DoSpaceForClone(void);

#define THROW_ERROR(vixError) \
   throw VixDiskLibErrWrapper((vixError), __FILE__, __LINE__)

#define CHECK_AND_THROW(vixError)                                    \
   do {                                                              \
      if (VIX_FAILED((vixError))) {                                  \
         throw VixDiskLibErrWrapper((vixError), __FILE__, __LINE__); \
      }                                                              \
   } while (0)

#ifdef DYNAMIC_LOADING

static VixError
(*VixDiskLib_InitEx_Ptr)(uint32 majorVersion,
                         uint32 minorVersion,
                         VixDiskLibGenericLogFunc *log,
                         VixDiskLibGenericLogFunc *warn,
                         VixDiskLibGenericLogFunc *panic,
                         const char* libDir,
                         const char* configFile);

static VixError
(*VixDiskLib_Init_Ptr)(uint32 majorVersion,
                       uint32 minorVersion,
                       VixDiskLibGenericLogFunc *log,
                       VixDiskLibGenericLogFunc *warn,
                       VixDiskLibGenericLogFunc *panic,
                       const char* libDir);

static void
(*VixDiskLib_Exit_Ptr)(void);

static const char *
(*VixDiskLib_ListTransportModes_Ptr)(void);


static VixError
(*VixDiskLib_Cleanup_Ptr)(const VixDiskLibConnectParams *connectParams,
                          uint32 *numCleanedUp, uint32 *numRemaining);

static VixError
(*VixDiskLib_Connect_Ptr)(const VixDiskLibConnectParams *connectParams,
                          VixDiskLibConnection *connection);

static VixError
(*VixDiskLib_ConnectEx_Ptr)(const VixDiskLibConnectParams *connectParams,
                            Bool readOnly,
                            const char *snapshotRef,
                            const char *transportModes,
                            VixDiskLibConnection *connection);

static VixError
(*VixDiskLib_Disconnect_Ptr)(VixDiskLibConnection connection);

static VixError
(*VixDiskLib_Create_Ptr)(const VixDiskLibConnection connection,
                         const char *path,
                         const VixDiskLibCreateParams *createParams,
                         VixDiskLibProgressFunc progressFunc,
                         void *progressCallbackData);

static VixError
(*VixDiskLib_CreateChild_Ptr)(VixDiskLibHandle diskHandle,
                              const char *childPath,
                              VixDiskLibDiskType diskType,
                              VixDiskLibProgressFunc progressFunc,
                              void *progressCallbackData);

static VixError
(*VixDiskLib_Open_Ptr)(const VixDiskLibConnection connection,
                       const char *path,
                       uint32 flags,
                       VixDiskLibHandle *diskHandle);

static VixError
(*VixDiskLib_GetInfo_Ptr)(VixDiskLibHandle diskHandle,
                          VixDiskLibInfo **info);

static void
(*VixDiskLib_FreeInfo_Ptr)(VixDiskLibInfo *info);


static const char *
(*VixDiskLib_GetTransportMode_Ptr)(VixDiskLibHandle diskHandle);

static VixError
(*VixDiskLib_Close_Ptr)(VixDiskLibHandle diskHandle);

static VixError
(*VixDiskLib_Read_Ptr)(VixDiskLibHandle diskHandle,
                       VixDiskLibSectorType startSector,
                       VixDiskLibSectorType numSectors,
                       uint8 *readBuffer);

static VixError
(*VixDiskLib_Write_Ptr)(VixDiskLibHandle diskHandle,
                        VixDiskLibSectorType startSector,
                        VixDiskLibSectorType numSectors,
                        const uint8 *writeBuffer);

static VixError
(*VixDiskLib_ReadMetadata_Ptr)(VixDiskLibHandle diskHandle,
                               const char *key,
                               char *buf,
                               size_t bufLen,
                               size_t *requiredLen);

static VixError
(*VixDiskLib_WriteMetadata_Ptr)(VixDiskLibHandle diskHandle,
                                const char *key,
                                const char *val);

static VixError
(*VixDiskLib_GetMetadataKeys_Ptr)(VixDiskLibHandle diskHandle,
                                  char *keys,
                                  size_t maxLen,
                                  size_t *requiredLen);

static VixError
(*VixDiskLib_Unlink_Ptr)(VixDiskLibConnection connection,
                         const char *path);

static VixError
(*VixDiskLib_Grow_Ptr)(VixDiskLibConnection connection,
                       const char *path,
                       VixDiskLibSectorType capacity,
                       Bool updateGeometry,
                       VixDiskLibProgressFunc progressFunc,
                       void *progressCallbackData);
static VixError
(*VixDiskLib_Shrink_Ptr)(VixDiskLibHandle diskHandle,
                         VixDiskLibProgressFunc progressFunc,
                         void *progressCallbackData);

static VixError
(*VixDiskLib_Defragment_Ptr)(VixDiskLibHandle diskHandle,
                             VixDiskLibProgressFunc progressFunc,
                             void *progressCallbackData);

static VixError
(*VixDiskLib_Rename_Ptr)(const char *srcFileName,
                         const char *dstFileName);

static VixError
(*VixDiskLib_Clone_Ptr)(const VixDiskLibConnection dstConnection,
                        const char *dstPath,
                        const VixDiskLibConnection srcConnection,
                        const char *srcPath,
                        const VixDiskLibCreateParams *vixCreateParams,
                        VixDiskLibProgressFunc progressFunc,
                        void *progressCallbackData,
                        Bool overWrite);

static char *
(*VixDiskLib_GetErrorText_Ptr)(VixError err, const char *locale);

static void
(*VixDiskLib_FreeErrorText_Ptr)(char* errMsg);

static VixError
(*VixDiskLib_Attach_Ptr)(VixDiskLibHandle parent, VixDiskLibHandle child);

static VixError
(*VixDiskLib_SpaceNeededForClone_Ptr)(VixDiskLibHandle diskHandle,
                                      VixDiskLibDiskType cloneDiskType,
                                      uint64* spaceNeeded);

static VixError
(*VixDiskLib_CheckRepair_Ptr)(const VixDiskLibConnection connection,
                              const char *filename,
                              Bool repair);

static VixError
(*VixMntapi_Init)(uint32 majorVersion,
                  uint32 minorVersion,
                  VixDiskLibGenericLogFunc *log,
                  VixDiskLibGenericLogFunc *warn,
                  VixDiskLibGenericLogFunc *panic,
                  const char *libDir,
                  const char *configFile);

static void
(*VixMntapi_Exit)(void);

static VixError
(*VixMntapi_OpenDisks)(VixDiskLibConnection connection,
                       const char *diskNames[],
                       size_t numberOfDisks,
                       uint32 openFlags,
                       VixDiskSetHandle *handle);
                       
static VixError
(*VixMntapi_OpenDiskSet)(VixDiskLibHandle diskHandles[],
                       	int numberOfDisks,
                       	uint32 openMode,
                       	VixDiskSetHandle *handle);                       

static VixError
(*VixMntapi_GetDiskSetInfo)(VixDiskSetHandle handle,
                            VixDiskSetInfo **diskSetInfo);

static void
(*VixMntapi_FreeDiskSetInfo)(VixDiskSetInfo *diskSetInfo);


static VixError
(*VixMntapi_CloseDiskSet)(VixDiskSetHandle diskSet);

static VixError
(*VixMntapi_GetVolumeHandles)(VixDiskSetHandle diskSet,
                              size_t *numberOfVolumes,
                              VixVolumeHandle *volumeHandles[]);

static void
(*VixMntapi_FreeVolumeHandles)(VixVolumeHandle *volumeHandles);

static VixError
(*VixMntapi_GetOsInfo)(VixDiskSetHandle diskSet, VixOsInfo **info);

static void
(*VixMntapi_FreeOsInfo)(VixOsInfo *info);

static VixError
(*VixMntapi_MountVolume)(VixVolumeHandle volumeHandle,
                         Bool readOnly);

static VixError
(*VixMntapi_DismountVolume)(VixVolumeHandle volumeHandle,
                            Bool force);

static VixError
(*VixMntapi_GetVolumeInfo)(VixVolumeHandle volumeHandle,
                           VixVolumeInfo **info);

static void
(*VixMntapi_FreeVolumeInfo)(VixVolumeInfo *info);

/*
 *----------------------------------------------------------------------
 *
 * LoadOneFunc --
 *
 *      Loads a single vixDiskLib function from shared library / DLL.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

#ifdef _WIN32
static void
LoadOneFunc(HINSTANCE hInstLib, void** pFunction, const char* funcName)
{
   std::stringstream strStream;
   *pFunction = GetProcAddress(hInstLib, funcName);
   if (*pFunction == NULL) {
      strStream << "Failed to load " << funcName << ". Error = " <<
         GetLastError() << "\n";
      throw std::runtime_error(strStream.str().c_str());
   }
}
#else
static void
LoadOneFunc(void* dlHandle, void** pFunction, const char* funcName)
{
   std::stringstream strStream;
   *pFunction = dlsym(dlHandle, funcName);
   char* dlErrStr = dlerror();
   if (*pFunction == NULL || dlErrStr != NULL) {
      strStream << "Failed to load " << funcName << ". Error = " <<
         dlErrStr << "\n";
      throw std::runtime_error(strStream.str().c_str());
   }
}
#endif

#define LOAD_ONE_FUNC(handle, funcName)  \
   LoadOneFunc(handle, (void**)&(funcName##_Ptr), #funcName)

#ifdef _WIN32
#define IS_HANDLE_INVALID(handle) ((handle) == INVALID_HANDLE_VALUE)
#else
#define IS_HANDLE_INVALID(handle) ((handle) == NULL)
#endif


/*
 *----------------------------------------------------------------------
 *
 * DynLoadDiskLib --
 *
 *      Dynamically loads VixDiskLib and bind to the functions.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DynLoadDiskLib(void)
{
#ifdef _WIN32
   HINSTANCE hInstLib = LoadLibrary("vixDiskLib.dll");
#else
   void* hInstLib = dlopen("libvixDiskLib.so", RTLD_LAZY);
   void* hMntInstLib = dlopen("libvixMntapi.so", RTLD_LAZY);
#endif

   // If the handle is valid, try to get the function address.
   if (IS_HANDLE_INVALID(hInstLib)) {
      cout << "Can't load vixDiskLib shared library / DLL : lasterror = " <<
#ifdef _WIN32
         GetLastError() <<
#else
         dlerror() <<
#endif
         "\n";

      exit(EXIT_FAILURE);
   }
   if (IS_HANDLE_INVALID(hMntInstLib)) {
      cout << "Can't load vixMntapi shared library / DLL : lasterror = " <<
#ifdef _WIN32
         GetLastError() <<
#else
         dlerror() <<
#endif
         "\n";

      exit(EXIT_FAILURE);
   }

   try {
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_InitEx);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Init);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Exit);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_ListTransportModes);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Cleanup);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Connect);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_ConnectEx);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Disconnect);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Create);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_CreateChild);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Open);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_GetInfo);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_FreeInfo);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_GetTransportMode);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Close);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Read);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Write);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_ReadMetadata);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_WriteMetadata);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_GetMetadataKeys);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Unlink);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Grow);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Shrink);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Defragment);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Rename);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Clone);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_GetErrorText);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_FreeErrorText);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_Attach);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_SpaceNeededForClone);
      LOAD_ONE_FUNC(hInstLib, VixDiskLib_CheckRepair);

      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_Init);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_Exit);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_OpenDiskSet);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_OpenDisks);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_GetDiskSetInfo);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_FreeDiskSetInfo);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_CloseDiskSet);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_GetVolumeHandles);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_FreeVolumeHandles);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_GetOsInfo);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_FreeOsInfo);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_MountVolume);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_DismountVolume);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_GetVolumeInfo);
      LOAD_ONE_FUNC(hMntInstLib, VixMntapi_FreeVolumeInfo);
   } catch (const std::runtime_error& exc) {
      cout << "Error while dynamically loading : " << exc.what() << "\n";
      exit(EXIT_FAILURE);
   }
}


#define VixDiskLib_InitEx           (*VixDiskLib_InitEx_Ptr)
#define VixDiskLib_Init             (*VixDiskLib_Init_Ptr)
#define VixDiskLib_Exit             (*VixDiskLib_Exit_Ptr)
#define VixDiskLib_ListTransportModes   (*VixDiskLib_ListTransportModes_Ptr)
#define VixDiskLib_Cleanup          (*VixDiskLib_Cleanup_Ptr)
#define VixDiskLib_Connect          (*VixDiskLib_Connect_Ptr)
#define VixDiskLib_ConnectEx        (*VixDiskLib_ConnectEx_Ptr)
#define VixDiskLib_Disconnect       (*VixDiskLib_Disconnect_Ptr)
#define VixDiskLib_Create           (*VixDiskLib_Create_Ptr)
#define VixDiskLib_CreateChild      (*VixDiskLib_CreateChild_Ptr)
#define VixDiskLib_Open             (*VixDiskLib_Open_Ptr)
#define VixDiskLib_GetInfo          (*VixDiskLib_GetInfo_Ptr)
#define VixDiskLib_FreeInfo         (*VixDiskLib_FreeInfo_Ptr)
#define VixDiskLib_GetTransportMode (*VixDiskLib_GetTransportMode_Ptr)
#define VixDiskLib_Close            (*VixDiskLib_Close_Ptr)
#define VixDiskLib_Read             (*VixDiskLib_Read_Ptr)
#define VixDiskLib_Write            (*VixDiskLib_Write_Ptr)
#define VixDiskLib_ReadMetadata     (*VixDiskLib_ReadMetadata_Ptr)
#define VixDiskLib_WriteMetadata    (*VixDiskLib_WriteMetadata_Ptr)
#define VixDiskLib_GetMetadataKeys  (*VixDiskLib_GetMetadataKeys_Ptr)
#define VixDiskLib_Unlink           (*VixDiskLib_Unlink_Ptr)
#define VixDiskLib_Grow             (*VixDiskLib_Grow_Ptr)
#define VixDiskLib_Shrink           (*VixDiskLib_Shrink_Ptr)
#define VixDiskLib_Defragment       (*VixDiskLib_Defragment_Ptr)
#define VixDiskLib_Rename           (*VixDiskLib_Rename_Ptr)
#define VixDiskLib_Clone            (*VixDiskLib_Clone_Ptr)
#define VixDiskLib_GetErrorText     (*VixDiskLib_GetErrorText_Ptr)
#define VixDiskLib_FreeErrorText    (*VixDiskLib_FreeErrorText_Ptr)
#define VixDiskLib_Attach           (*VixDiskLib_Attach_Ptr)
#define VixDiskLib_SpaceNeededForClone   (*VixDiskLib_SpaceNeededForClone_Ptr)
#define VixDiskLib_CheckRepair      (*VixDiskLib_CheckRepair_Ptr)

#define VixMntapi_Init,             (*VixMntapi_Init_Ptr)
#define VixMntapi_Exit,             (*VixMntapi_Exit_Ptr)
#define VixMntapi_OpenDiskSet,      (*VixMntapi_OpenDiskSet_Ptr)
#define VixMntapi_OpenDisks,        (*VixMntapi_OpenDisks_Ptr)
#define VixMntapi_GetDiskSetInfo,   (*VixMntapi_GetDiskSetInfo_Ptr)
#define VixMntapi_FreeDiskSetInfo,  (*VixMntapi_FreeDiskSetInfo_Ptr)
#define VixMntapi_CloseDiskSet,     (*VixMntapi_CloseDiskSet_Ptr)
#define VixMntapi_GetVolumeHandles, (*VixMntapi_GetVolumeHandles_Ptr)
#define VixMntapi_FreeVolumeHandles,(*VixMntapi_FreeVolumeHandles_Ptr)
#define VixMntapi_GetOsInfo,        (*VixMntapi_GetOsInfo_Ptr)
#define VixMntapi_FreeOsInfo,       (*VixMntapi_FreeOsInfo_Ptr)
#define VixMntapi_MountVolume,      (*VixMntapi_MountVolume_Ptr)
#define VixMntapi_DismountVolume,   (*VixMntapi_DismountVolume_Ptr)
#define VixMntapi_GetVolumeInfo,    (*VixMntapi_GetVolumeInfo_Ptr)
#define VixMntapi_FreeVolumeInfo,   (*VixMntapi_FreeVolumeInfo_Ptr)

#endif // DYNAMIC_LOADING



#ifdef _WIN32

/*
 *----------------------------------------------------------------------
 *
 * gettimeofday --
 *
 *      Mimics BSD style gettimeofday in a way that is close enough
 *      for some I/O benchmarking.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
gettimeofday(struct timeval *tv,
             void *)
{
   uint64 ticks = GetTickCount();

   tv->tv_sec = ticks / 1000;
   tv->tv_usec = 1000 * (ticks % 1000);
}

#endif


/*
 *--------------------------------------------------------------------------
 *
 * LogFunc --
 *
 *      Callback for VixDiskLib Log messages.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
LogFunc(const char *fmt, va_list args)
{
   printf("Log: ");
   vprintf(fmt, args);
}


/*
 *--------------------------------------------------------------------------
 *
 * WarnFunc --
 *
 *      Callback for VixDiskLib Warning messages.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
WarnFunc(const char *fmt, va_list args)
{
   printf("Warning: ");
   vprintf(fmt, args);
}


/*
 *--------------------------------------------------------------------------
 *
 * PanicFunc --
 *
 *      Callback for VixDiskLib Panic messages.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
PanicFunc(const char *fmt, va_list args)
{
   printf("Panic: ");
   vprintf(fmt, args);
   exit(10);
}

typedef void (VixDiskLibGenericLogFunc)(const char *fmt, va_list args);


// Wrapper class for VixDiskLib disk objects.

class VixDiskLibErrWrapper
{
public:
    explicit VixDiskLibErrWrapper(VixError errCode, const char* file, int line)
          :
          _errCode(errCode),
          _file(file),
          _line(line)
    {
        char* msg = VixDiskLib_GetErrorText(errCode, NULL);
        _desc = msg;
        VixDiskLib_FreeErrorText(msg);
    }

    VixDiskLibErrWrapper(const char* description, const char* file, int line)
          :
         _errCode(VIX_E_FAIL),
         _desc(description),
         _file(file),
         _line(line)
    {
    }

    string Description() const { return _desc; }
    VixError ErrorCode() const { return _errCode; }
    string File() const { return _file; }
    int Line() const { return _line; }

private:
    VixError _errCode;
    string _desc;
    string _file;
    int _line;
};

class VixDisk
{
public:

    VixDiskLibHandle Handle() { return _handle; }
    VixDisk(VixDiskLibConnection connection, char *path, uint32 flags)
    {
       _handle = NULL;
       VixError vixError = VixDiskLib_Open(connection, path, flags, &_handle);
       CHECK_AND_THROW(vixError);
       printf("Disk \"%s\" is open using transport mode \"%s\".\n",
              path, VixDiskLib_GetTransportMode(_handle));
    }

    ~VixDisk()
    {
        if (_handle) {
           VixDiskLib_Close(_handle);
        }
        _handle = NULL;
    }

private:
    VixDiskLibHandle _handle;
};

class VixDisks
{
public:

    VixDiskSetHandle Handle() { return _handle; }
    VixDisks(VixDiskLibConnection connection, const char *paths[], size_t numberOfDisks, uint32 flags)
    {
       _handle = NULL;
       VixError vixError = VixMntapi_OpenDisks(connection, paths, numberOfDisks, flags, &_handle);
       CHECK_AND_THROW(vixError);
    }

    ~VixDisks()
    {
        if (_handle) 
        {
           VixMntapi_CloseDiskSet(_handle);
        }
        _handle = NULL;
    }

private:
    VixDiskSetHandle _handle;
};

/* --------------------------------------------------------------------------
 * This is applicable to WIN32 Platform
class VixDiskSet
{
public:

    VixDiskSetHandle Handle() { return _handle; }
    VixDiskSet(VixDiskLibConnection connection, const char *paths[], int numberOfDisks, uint32 flags)
    {
		_numberOfDisks = numberOfDisks;
		_diskHandles = new VixDiskLibHandle[_numberOfDisks];
		for (int i=0; i< _numberOfDisks; i++) {
			_diskHandles[i] = NULL;
		}
		for (int i=0; i<_numberOfDisks; i++) {
			VixDiskLibHandle diskHandle = NULL;
			VixError vixError =  VixDiskLib_Open(connection, paths[i], flags, &diskHandle);
			CHECK_AND_THROW(vixError);
			_diskHandles[i] = diskHandle;
		}

		_handle = NULL;
		VixError vixError = VixMntapi_OpenDiskSet(_diskHandles, _numberOfDisks, flags, &_handle);
		CHECK_AND_THROW(vixError);
    }

    ~VixDiskSet()
    {
		for (int i=0; i<_numberOfDisks; i++) {
			if (_diskHandles[i] != NULL) { 
				VixDiskLib_Close(_diskHandles[i]);
			}
		} 
		delete [] _diskHandles; 
		  
        if (_handle) 
        {
           VixMntapi_CloseDiskSet(_handle);
        }
        _handle = NULL;
    }

private:
    VixDiskSetHandle _handle;
	int _numberOfDisks;
	VixDiskLibHandle* _diskHandles;
};

--------------------------------------------------------------------------*/

/*
 *--------------------------------------------------------------------------
 *
 * PrintUsage --
 *
 *      Displays the usage message.
 *
 * Results:
 *      1.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static int
PrintUsage(void)
{
    printf("Usage: trilio-vix-disk-cli command [options] diskPath\n");
    printf("commands:\n");
    printf(" -create : creates a sparse virtual disk with capacity "
           "specified by -cap\n");
    printf(" -redo parentPath : creates a redo log 'diskPath' "
           "for base disk 'parentPath'\n");
    printf(" -info : displays information for specified virtual disk\n");
    printf(" -dump : dumps the contents of specified range of sectors "
           "in hexadecimal\n");
    printf(" -fill : fills specified range of sectors with byte value "
           "specified by -val\n");
    printf(" -download remotePath: downloads the data from remote disk to local disk\n"
           "  with the extent specified by -start -count parameters\n");
    printf(" -upload localPath: uploads the data from the local disk to remote disk\n"
           "  with the extent specified by -start -count parameters\n");
    printf(" -downloadextents remotePath: downloads the data from remote disk to local disk\n"
           "  with the extents specified by -extentfile parameter\n");
    printf(" -uploadextents localPath: uploads the data from the local disk to remote disk\n"
           "  with the extents specified by -extentfile parameter\n");
    printf(" -compare localPath: Compares contents of the local disk to remote disk\n");
    printf(" -copy sourcePath: Copies contents of the source disk to another local disk\n");    
    printf(" -attach parentPath: Attaches the child disk to parent disk\n");    
    printf(" -wmeta key value : writes (key,value) entry into disk's metadata table\n");
    printf(" -rmeta key : displays the value of the specified metada entry\n");
    printf(" -meta : dumps all entries of the disk's metadata\n");
    printf(" -clone sourcePath : clone source vmdk possibly to a remote site\n");
    printf(" -readbench blocksize: Does a read benchmark on a disk using the \n");
    printf("\tspecified I/O block size (in sectors).\n");
    printf(" -writebench blocksize: Does a write benchmark on a disk using the\n");
    printf("\tspecified I/O block size (in sectors). WARNING: This will\n");
    printf("\toverwrite the contents of the disk specified.\n");
    printf(" -mount mounts virtual disks specified in diskPath. Mountpoints will be written to the\n"
    	   " file specified by -mountpointsfile. -diskonly mounts disk but not volumes\n");
    printf(" -unmount unmounts a virtual disk that was previously mounted using -mount option.\n");
    printf(" -spaceforclone computes the space required for clone for the specified disk type.\n");


    printf("\n\n");
    printf("options:\n");
    printf(" -adapter [ide|scsi] : bus adapter type for 'create' option "
           "\t(default='scsi')\n");
    printf(" -start n : start sector for 'dump/fill' options (default=0)\n");
    printf(" -count n : number of sectors for 'dump/fill' options (default=1)\n");
    printf(" -val byte : byte value to fill with for 'write' option (default=255)\n");
    printf(" -extentfile filename: file name that has all the extents the format (start, length)\n");
    printf(" -mountpointsfile filename: file name where all the mount points are listed after mount operation\n");
    printf(" -diskonly : Mounts disk but not any volumes on the disk\n");
    printf(" -cap megabytes : capacity in MB for -create option (default=100)\n");
    printf(" -single : open file as single disk link (default=open entire chain)\n");
    printf(" -multithread n: start n threads and copy the file to n new files\n");
    printf(" -host hostname : hostname / IP addresss (ESX 3.x or VC 2.x) \n");
    printf(" -user userid : user name on host (default = root) \n");
    printf(" -password password : password on host \n");
    printf(" -port port : port to use to connect to host (default = 902) \n");
    printf(" -vm vmPath=/path/to/vm : inventory path to vm that owns the virtual disk \n");
    printf(" -libdir dir : Directory containing vixDiskLibPlugin library \n");
    printf(" -initex configfile : Use VixDiskLib_InitEx\n");
    printf(" -ssmoref moref : Managed object reference of VM snapshot \n");
    printf(" -mode mode : Mode string to pass into VixDiskLib_ConnectEx \n");
    printf(" -thumb string : Provides a SSL thumbprint string for validation.\n");
    printf(" -check repair: Check a sparse disk for internal consistency.\n");
    return 1;
}


/*
 *--------------------------------------------------------------------------
 *
 * main --
 *
 *      Main routine of the program.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

int
main(int argc, char* argv[])
{
    int retval;
    bool bVixInit(false);

    memset(&appGlobals, 0, sizeof appGlobals);
    appGlobals.command = 0;
    appGlobals.adapterType = VIXDISKLIB_ADAPTER_SCSI_BUSLOGIC;
    appGlobals.startSector = 0;
    appGlobals.numSectors = 1;
    appGlobals.mbSize = 100;
    appGlobals.filler = 0xff;
    appGlobals.openFlags = 0;
    appGlobals.numThreads = 1;
    appGlobals.success = TRUE;
    appGlobals.isRemote = FALSE;

	cout << "Water Mark: Before ParseArguments" << endl;
    retval = ParseArguments(argc, argv);
    if (retval) {
        return retval;
    }
	cout << "Water Mark: After ParseArguments" << endl;

#ifdef DYNAMIC_LOADING
    DynLoadDiskLib();
#endif

    VixDiskLibConnectParams cnxParams = {0};
    VixError vixError;
    try {
       if (appGlobals.isRemote) {
          cnxParams.vmxSpec = appGlobals.vmxSpec;
          cnxParams.serverName = appGlobals.host;
          cnxParams.credType = VIXDISKLIB_CRED_UID;
          cnxParams.creds.uid.userName = appGlobals.userName;
          cnxParams.creds.uid.password = appGlobals.password;
          cnxParams.thumbPrint = appGlobals.thumbPrint;
          cnxParams.port = appGlobals.port;
       }

       if (appGlobals.useInitEx) {
          vixError = VixDiskLib_InitEx(VIXDISKLIB_VERSION_MAJOR,
                                       VIXDISKLIB_VERSION_MINOR,
                                       &LogFunc, &WarnFunc, &PanicFunc,
                                       appGlobals.libdir,
                                       appGlobals.cfgFile);
       } else {
          vixError = VixDiskLib_Init(VIXDISKLIB_VERSION_MAJOR,
                                     VIXDISKLIB_VERSION_MINOR,
                                     NULL, NULL, NULL, // Log, warn, panic
                                     appGlobals.libdir);
          CHECK_AND_THROW(vixError);
          vixError = VixMntapi_Init(VIXMNTAPI_MAJOR_VERSION,
                                    VIXMNTAPI_MINOR_VERSION,
                                    NULL, NULL, NULL, // Log, warn, panic
                                    appGlobals.libdir, NULL);
       }
       CHECK_AND_THROW(vixError);
       bVixInit = true;

       if (appGlobals.vmxSpec != NULL) {
          vixError = VixDiskLib_PrepareForAccess(&cnxParams, "trilioVault");
       }
       if (appGlobals.ssMoRef == NULL && appGlobals.transportModes == NULL) {
          vixError = VixDiskLib_Connect(&cnxParams,
                                        &appGlobals.connection);
       } else {
          Bool ro = (appGlobals.openFlags & VIXDISKLIB_FLAG_OPEN_READ_ONLY);
          vixError = VixDiskLib_ConnectEx(&cnxParams, ro, appGlobals.ssMoRef,
                                          appGlobals.transportModes,
                                          &appGlobals.connection);
       }
       CHECK_AND_THROW(vixError);
        if (appGlobals.command & COMMAND_INFO) {
            DoInfo();
        } else if (appGlobals.command & COMMAND_CREATE) {
            DoCreate();
        } else if (appGlobals.command & COMMAND_REDO) {
            DoRedo();
        } else if (appGlobals.command & COMMAND_FILL) {
            DoFill();
        } else if (appGlobals.command & COMMAND_DOWNLOAD) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoDownload();
        } else if (appGlobals.command & COMMAND_UPLOAD) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoUpload();
        } else if (appGlobals.command & COMMAND_DOWNLOADEXTENTS) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoDownloadExtents();
        } else if (appGlobals.command & COMMAND_UPLOADEXTENTS) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoUploadExtents();
        } else if (appGlobals.command & COMMAND_COMPARE) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoCompare();
        } else if (appGlobals.command & COMMAND_SPACE_FOR_CLONE) {
            DoSpaceForClone();            
        } else if (appGlobals.command & COMMAND_DUMP) {
            DoDump();
        } else if (appGlobals.command & COMMAND_READ_META) {
            DoReadMetadata();
        } else if (appGlobals.command & COMMAND_WRITE_META) {
            DoWriteMetadata();
        } else if (appGlobals.command & COMMAND_DUMP_META) {
            DoDumpMetadata();
        } else if (appGlobals.command & COMMAND_MULTITHREAD) {
            DoTestMultiThread();
        } else if (appGlobals.command & COMMAND_CLONE) {
            DoClone();
        } else if (appGlobals.command & COMMAND_READBENCH) {
            DoRWBench(true);
        } else if (appGlobals.command & COMMAND_WRITEBENCH) {
            DoRWBench(false);
        } else if (appGlobals.command & COMMAND_CHECKREPAIR) {
            DoCheckRepair(appGlobals.repair);
        } else if (appGlobals.command & COMMAND_MOUNT) {
            DoMount();
        } else if (appGlobals.command & COMMAND_UNMOUNT) {
            DoUnmount();
        } else if (appGlobals.command & COMMAND_COPY) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoCopy();
        } else if (appGlobals.command & COMMAND_ATTACH) {
            VixDiskLibConnectParams cnxParams = {0};
            vixError = VixDiskLib_Connect(&cnxParams, &appGlobals.localConnection);
            CHECK_AND_THROW(vixError);
            DoAttach();
        }
        retval = 0;
    } catch (const VixDiskLibErrWrapper& e) {
       cout << "Error: [" << e.File() << ":" << e.Line() << "]  " <<
               std::hex << e.ErrorCode() << " " << e.Description() << "\n";
       retval = 1;
    }

    if (appGlobals.vmxSpec != NULL) {
       vixError = VixDiskLib_EndAccess(&cnxParams, "trilioVault");
    }
    if (appGlobals.connection != NULL) {
       VixDiskLib_Disconnect(appGlobals.connection);
    }
    if (bVixInit) {
       VixDiskLib_Exit();
    }
    return retval;
}


/*
 *--------------------------------------------------------------------------
 *
 * ParseArguments --
 *
 *      Parses the arguments passed on the command line.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static int
ParseArguments(int argc, char* argv[])
{
    int i;
    /*
    for (i = 1; i < argc; i++) {
    	cout << argv[i] << endl;
    } 
    */   
    if (argc < 3) {
        return PrintUsage();
    }
    appGlobals.source = "local";
    for (i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-info")) {
            appGlobals.command |= COMMAND_INFO;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
        } else if (!strcmp(argv[i], "-create")) {
            appGlobals.command |= COMMAND_CREATE;
        } else if (!strcmp(argv[i], "-dump")) {
            appGlobals.command |= COMMAND_DUMP;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
        } else if (!strcmp(argv[i], "-fill")) {
            appGlobals.command |= COMMAND_FILL;
        } else if (!strcmp(argv[i], "-mount")) {
            appGlobals.command |= COMMAND_MOUNT;
        } else if (!strcmp(argv[i], "-unmount")) {
            appGlobals.command |= COMMAND_UNMOUNT;
        } else if (!strcmp(argv[i], "-meta")) {
            appGlobals.command |= COMMAND_DUMP_META;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
        } else if (!strcmp(argv[i], "-single")) {
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_SINGLE_LINK;
        } else if (!strcmp(argv[i], "-adapter")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.adapterType = strcmp(argv[i], "scsi") == 0 ?
                                       VIXDISKLIB_ADAPTER_SCSI_BUSLOGIC :
                                       VIXDISKLIB_ADAPTER_IDE;
            ++i;
        } else if (!strcmp(argv[i], "-rmeta")) {
            appGlobals.command |= COMMAND_READ_META;
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.metaKey = argv[++i];
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
        } else if (!strcmp(argv[i], "-wmeta")) {
            appGlobals.command |= COMMAND_WRITE_META;
            if (i >= argc - 3) {
                return PrintUsage();
            }
            appGlobals.metaKey = argv[++i];
            appGlobals.metaVal = argv[++i];
        } else if (!strcmp(argv[i], "-redo")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_REDO;
            appGlobals.parentPath = argv[++i];
        } else if (!strcmp(argv[i], "-download")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_DOWNLOAD;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
            appGlobals.remotePath = argv[++i];
        } else if (!strcmp(argv[i], "-upload")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_UPLOAD;
            appGlobals.localPath = argv[++i];
        } else if (!strcmp(argv[i], "-downloadextents")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_DOWNLOADEXTENTS;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
            appGlobals.remotePath = argv[++i];
        } else if (!strcmp(argv[i], "-uploadextents")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_UPLOADEXTENTS;
            appGlobals.localPath = argv[++i];
        } else if (!strcmp(argv[i], "-compare")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_COMPARE;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
            appGlobals.localPath = argv[++i];
        } else if (!strcmp(argv[i], "-spaceforclone")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_SPACE_FOR_CLONE;
            appGlobals.diskType = argv[++i];                
        } else if (!strcmp(argv[i], "-copy")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_COPY;
            appGlobals.srcPath = argv[++i];
        } else if (!strcmp(argv[i], "-val")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.filler = strtol(argv[++i], NULL, 0);
        } else if (!strcmp(argv[i], "-start")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.startSector = strtol(argv[++i], NULL, 0);
        } else if (!strcmp(argv[i], "-extentfile")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.extentfile = argv[++i];
        } else if (!strcmp(argv[i], "-mountpointsfile")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.mountpointsfile = argv[++i];            
        } else if (!strcmp(argv[i], "-diskonly")) {
            appGlobals.diskonlymount = 1;
        } else if (!strcmp(argv[i], "-parentPath")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.parentPath = argv[++i];
        } else if (!strcmp(argv[i], "-count")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.numSectors = strtol(argv[++i], NULL, 0);
        } else if (!strcmp(argv[i], "-cap")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.mbSize = strtol(argv[++i], NULL, 0);
        } else if (!strcmp(argv[i], "-clone")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.srcPath = argv[++i];
            appGlobals.command |= COMMAND_CLONE;
        } else if (!strcmp(argv[i], "-source")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.source = argv[++i];
        } else if (!strcmp(argv[i], "-attach")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_ATTACH;
            appGlobals.parentPath = argv[++i];
        } else if (!strcmp(argv[i], "-readbench")) {
            if (0 && i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.bufSize = strtol(argv[++i], NULL, 0);
            appGlobals.command |= COMMAND_READBENCH;
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
        } else if (!strcmp(argv[i], "-writebench")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.bufSize = strtol(argv[++i], NULL, 0);
            appGlobals.command |= COMMAND_WRITEBENCH;
        } else if (!strcmp(argv[i], "-multithread")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_MULTITHREAD;
            appGlobals.numThreads = strtol(argv[++i], NULL, 0);
            appGlobals.openFlags |= VIXDISKLIB_FLAG_OPEN_READ_ONLY;
        } else if (!strcmp(argv[i], "-host")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.host = argv[++i];
            appGlobals.isRemote = TRUE;
        } else if (!strcmp(argv[i], "-user")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.userName = argv[++i];
            appGlobals.isRemote = TRUE;
        } else if (!strcmp(argv[i], "-password")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.password = argv[++i];
            appGlobals.isRemote = TRUE;
        } else if (!strcmp(argv[i], "-thumb")) {
            if (i >= argc - 2) {
               return PrintUsage();
            }
            appGlobals.thumbPrint = argv[++i];
            appGlobals.isRemote = TRUE;
        } else if (!strcmp(argv[i], "-port")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.port = strtol(argv[++i], NULL, 0);
            appGlobals.isRemote = TRUE;
        } else if (!strcmp(argv[i], "-vm")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.vmxSpec = argv[++i];
            appGlobals.isRemote = TRUE;
        } else if (!strcmp(argv[i], "-libdir")) {
           if (i >= argc - 2) {
              return PrintUsage();
           }
           appGlobals.libdir = argv[++i];
        } else if (!strcmp(argv[i], "-initex")) {
           if (i >= argc - 2) {
              return PrintUsage();
           }
           appGlobals.useInitEx = true;
           appGlobals.cfgFile = argv[++i];
           if (appGlobals.cfgFile[0] == '\0') {
              appGlobals.cfgFile = NULL;
           }
        } else if (!strcmp(argv[i], "-ssmoref")) {
           if (i >= argc - 2) {
              return PrintUsage();
           }
           appGlobals.ssMoRef = argv[++i];
        } else if (!strcmp(argv[i], "-mode")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.transportModes = argv[++i];
        } else if (!strcmp(argv[i], "-check")) {
            if (i >= argc - 2) {
                return PrintUsage();
            }
            appGlobals.command |= COMMAND_CHECKREPAIR;
            appGlobals.repair = strtol(argv[++i], NULL, 0);
        } else {
           return PrintUsage();
        }
    }
    appGlobals.diskPath = argv[i];

    if (BitCount(appGlobals.command) != 1) {
       return PrintUsage();
    }

    if (appGlobals.isRemote) {
       if (appGlobals.port == 0) {
          appGlobals.port = 902;
       }

       if (appGlobals.host == NULL ||
           appGlobals.userName == NULL ||
           appGlobals.password == NULL) {
           return PrintUsage();
       }
    }

    /*
     * TODO: More error checking for params, really
     */
    return 0;
}


/*
 *--------------------------------------------------------------------------
 *
 * DoInfo --
 *
 *      Queries the information of a virtual disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoInfo(void)
{
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    VixDiskLibInfo *info = NULL;
    VixError vixError;

    vixError = VixDiskLib_GetInfo(disk.Handle(), &info);

    CHECK_AND_THROW(vixError);

    cout << "capacity          = " << info->capacity << " sectors" << endl;
    cout << "number of links   = " << info->numLinks << endl;
    cout << "adapter type      = ";
    switch (info->adapterType) {
    case VIXDISKLIB_ADAPTER_IDE:
       cout << "IDE" << endl;
       break;
    case VIXDISKLIB_ADAPTER_SCSI_BUSLOGIC:
       cout << "BusLogic SCSI" << endl;
       break;
    case VIXDISKLIB_ADAPTER_SCSI_LSILOGIC:
       cout << "LsiLogic SCSI" << endl;
       break;
    default:
       cout << "unknown" << endl;
       break;
    }

    cout << "BIOS geometry     = " << info->biosGeo.cylinders <<
       "/" << info->biosGeo.heads << "/" << info->biosGeo.sectors << endl;

    cout << "physical geometry = " << info->physGeo.cylinders <<
       "/" << info->physGeo.heads << "/" << info->physGeo.sectors << endl;

    VixDiskLib_FreeInfo(info);

    cout << "Transport modes supported by vixDiskLib: " <<
       VixDiskLib_ListTransportModes() << endl;
}


/*
 *--------------------------------------------------------------------------
 *
 * DoCreate --
 *
 *      Creates a virtual disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoCreate(void)
{
   VixDiskLibCreateParams createParams;
   VixError vixError;

   createParams.adapterType = appGlobals.adapterType;

   createParams.capacity = appGlobals.mbSize * 2048;
   createParams.diskType = VIXDISKLIB_DISK_MONOLITHIC_SPARSE;
   createParams.hwVersion = VIXDISKLIB_HWVERSION_WORKSTATION_5;

   vixError = VixDiskLib_Create(appGlobals.connection,
                                appGlobals.diskPath,
                                &createParams,
                                NULL,
                                NULL);
   CHECK_AND_THROW(vixError);
}


/*
 *--------------------------------------------------------------------------
 *
 * DoRedo --
 *
 *      Creates a child disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoRedo(void)
{
   VixError vixError;
   VixDisk parentDisk(appGlobals.connection, appGlobals.parentPath, 0);
   vixError = VixDiskLib_CreateChild(parentDisk.Handle(),
                                     appGlobals.diskPath,
                                     VIXDISKLIB_DISK_MONOLITHIC_SPARSE,
                                     NULL, NULL);
   CHECK_AND_THROW(vixError);
}


/*
 *--------------------------------------------------------------------------
 *
 * DoFill --
 *
 *      Writes to a virtual disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoFill(void)
{
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    uint8 buf[VIXDISKLIB_SECTOR_SIZE];
    VixDiskLibSectorType startSector;

    memset(buf, appGlobals.filler, sizeof buf);

    for (startSector = 0; startSector < appGlobals.numSectors; ++startSector) {
       VixError vixError;
       vixError = VixDiskLib_Write(disk.Handle(),
                                   appGlobals.startSector + startSector,
                                   1, buf);
       CHECK_AND_THROW(vixError);
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoDownload --
 *
 *      Downloads an extent from a remote disk to local disk
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoDownload(void)
{
    uint32 localFlags = appGlobals.openFlags & ~VIXDISKLIB_FLAG_OPEN_READ_ONLY;
    VixDisk localDisk(appGlobals.localConnection, appGlobals.diskPath, localFlags);
    VixDisk remoteDisk(appGlobals.connection, appGlobals.remotePath, appGlobals.openFlags);
    uint8 buf[VIXDISKLIB_BUF_SIZE];
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibSectorType i;
    VixError vixError;
    
    numSectors = appGlobals.numSectors;
    startSector = appGlobals.startSector;

    while (numSectors)
    {
        
        VixDiskLibSectorType nsec = (numSectors >= VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE) ?
                                      VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE : numSectors;

        // Read from remote disk and copy it to local disk
        vixError = VixDiskLib_Read(remoteDisk.Handle(),
                                   startSector,
                                   nsec, buf);
        CHECK_AND_THROW(vixError);

        vixError = VixDiskLib_Write(localDisk.Handle(),
                                    startSector,
                                    nsec, buf);
        CHECK_AND_THROW(vixError);
        startSector += nsec;
        numSectors -= nsec;
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoCompare --
 *
 *      Compares contents of a local disk to remote disk 
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoCompare(void)
{
    VixDisk localDisk(appGlobals.localConnection, appGlobals.localPath, appGlobals.openFlags);
    VixDisk remoteDisk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    uint8 buf1[VIXDISKLIB_BUF_SIZE];
    uint8 buf2[VIXDISKLIB_BUF_SIZE];
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibInfo *info = NULL;
    VixDiskLibSectorType i;
    VixError vixError;
    
    vixError = VixDiskLib_GetInfo(localDisk.Handle(), &info);
    CHECK_AND_THROW(vixError);
    numSectors = info->capacity;
    startSector = 0;

    VixDiskLib_FreeInfo(info);

    vixError = VixDiskLib_GetInfo(remoteDisk.Handle(), &info);
    VixDiskLibSectorType rsec = info->capacity;
    VixDiskLib_FreeInfo(info);

    if (numSectors != rsec)
    {
        CHECK_AND_THROW(VIX_E_DISK_CAPACITY_MISMATCH);
    }

    while (numSectors)
    {
        
        VixDiskLibSectorType nsec = (numSectors >= VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE) ?
                                     VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE : numSectors;

        // Read from remote disk and copy it to local disk
        vixError = VixDiskLib_Read(localDisk.Handle(),
                                   startSector,
                                   nsec, buf1);
        CHECK_AND_THROW(vixError);

        vixError = VixDiskLib_Read(remoteDisk.Handle(),
                                    startSector,
                                    nsec, buf2);
        CHECK_AND_THROW(vixError);

        if (memcmp(buf1, buf2, VIXDISKLIB_BUF_SIZE))
        {
            CHECK_AND_THROW(VIX_E_FAIL);
        }
        numSectors -= nsec;
        startSector += nsec;
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoUpload --
 *
 *      Uploads an extent from a local disk to remote disk 
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoUpload(void)
{
    VixDisk localDisk(appGlobals.localConnection, appGlobals.localPath, appGlobals.openFlags);
    VixDisk remoteDisk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    uint8 buf[VIXDISKLIB_BUF_SIZE];
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibSectorType i;
    VixError vixError;
    
    numSectors = appGlobals.numSectors;
    startSector = appGlobals.startSector;

    while (numSectors)
    {
        
        VixDiskLibSectorType nsec = (numSectors >= VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE) ?
                                     VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE : numSectors;

        // Read from remote disk and copy it to local disk
        vixError = VixDiskLib_Read(localDisk.Handle(),
                                   startSector,
                                   nsec, buf);
        CHECK_AND_THROW(vixError);

        vixError = VixDiskLib_Write(remoteDisk.Handle(),
                                    startSector,
                                    nsec, buf);
        CHECK_AND_THROW(vixError);
        numSectors -= nsec;
        startSector += nsec;
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoUploadExtents --
 *
 *      UploadExtents list of extents identified in the extents file
 *      from local path to remote path
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoUploadExtents(void)
{
    VixDisk localDisk(appGlobals.localConnection, appGlobals.localPath, appGlobals.openFlags);
    VixDisk remoteDisk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    uint8 buf[VIXDISKLIB_BUF_SIZE];
    VixDiskLibSectorType totalBytesTransferred = 0;
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibSectorType i;
    VixError vixError;
    
    std::string delimiter = ",";
    string line;
    ifstream myfile(appGlobals.extentfile);
    size_t pos = 0;
    std::string token;
    unsigned long num;

    if (myfile.is_open())
    {
        while ( getline (myfile, line) )
        {
            line.erase(line.begin(), std::find_if(line.begin(), line.end(),
                       std::bind1st(std::not_equal_to<char>(), ' ')));
            while ((pos = line.find(delimiter)) != std::string::npos) 
            {
                token = line.substr(0, pos);
                startSector = std::stoul (token,nullptr,0)/512;
                line.erase(0, pos + delimiter.length());
                line.erase(line.begin(), std::find_if(line.begin(), line.end(),
                           std::bind1st(std::not_equal_to<char>(), ' ')));
            }
            numSectors = std::stoul (line,nullptr,0)/512;

            while (numSectors)
            {
        
                VixDiskLibSectorType nsec = (numSectors >= VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE) ?
                                             VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE : numSectors;
    
                // Read from remote disk and copy it to local disk
                vixError = VixDiskLib_Read(localDisk.Handle(),
                                           startSector, nsec, buf);
                CHECK_AND_THROW(vixError);
    
                vixError = VixDiskLib_Write(remoteDisk.Handle(),
                                            startSector, nsec, buf);
                CHECK_AND_THROW(vixError);
                numSectors -= nsec;
                startSector += nsec;
                totalBytesTransferred += nsec * VIXDISKLIB_SECTOR_SIZE;
                if (totalBytesTransferred % (64 * 1024 * 1024) == 0)
                {
                    cout << "" << totalBytesTransferred << " Done" << endl;
                }
            }
        }
        cout << "" << totalBytesTransferred << " Done" << endl;
        myfile.close();
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoDownloadExtents --
 *
 *      DownloadExtents list of extents identified in the extents file
 *      from remote path to local path
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoDownloadExtents(void)
{
    VixError vixError;
    if (appGlobals.parentPath != NULL)
   	{
		VixDisk parentDisk(appGlobals.localConnection, appGlobals.parentPath, 0);
		vixError = VixDiskLib_CreateChild(parentDisk.Handle(),
	                                     appGlobals.diskPath,
	                                     VIXDISKLIB_DISK_MONOLITHIC_SPARSE,
	                                     NULL, NULL);
	    CHECK_AND_THROW(vixError);   	
   	}
    uint32 localFlags = appGlobals.openFlags & ~VIXDISKLIB_FLAG_OPEN_READ_ONLY;
    VixDisk localDisk(appGlobals.localConnection, appGlobals.diskPath, localFlags);
    VixDisk remoteDisk(appGlobals.connection, appGlobals.remotePath, appGlobals.openFlags);
    uint8 buf[VIXDISKLIB_BUF_SIZE];
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibSectorType totalBytesTransferred = 0;
    VixDiskLibSectorType i;

    std::string delimiter = ",";
    string line;
    ifstream myfile(appGlobals.extentfile);
    size_t pos = 0;
    size_t incr64mb = 1;
    std::string token;
    unsigned long num;

    if (myfile.is_open())
    {
        while ( getline (myfile, line) )
        {
            line.erase(line.begin(), std::find_if(line.begin(), line.end(),
                       std::bind1st(std::not_equal_to<char>(), ' ')));
            while ((pos = line.find(delimiter)) != std::string::npos) 
            {
                token = line.substr(0, pos);
                startSector = std::stoul (token,nullptr,0)/512;
                line.erase(0, pos + delimiter.length());
                line.erase(line.begin(), std::find_if(line.begin(), line.end(),
                           std::bind1st(std::not_equal_to<char>(), ' ')));
            }
            numSectors = std::stoul (line,nullptr,0)/512;

            while (numSectors)
            {
                VixDiskLibSectorType nsec = (numSectors >= VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE) ?
                                              VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE : numSectors;

                // Read from remote disk and copy it to local disk
                vixError = VixDiskLib_Read(remoteDisk.Handle(),
                                           startSector, nsec, buf);
                CHECK_AND_THROW(vixError);

                vixError = VixDiskLib_Write(localDisk.Handle(),
                                            startSector, nsec, buf);
                CHECK_AND_THROW(vixError);
                startSector += nsec;
                numSectors -= nsec;
                totalBytesTransferred += nsec * VIXDISKLIB_SECTOR_SIZE;
                if (totalBytesTransferred > (incr64mb * 64 * 1024 * 1024))
                {
                    incr64mb ++;
                    cout << "" << totalBytesTransferred << " Done" << endl;
                }
            }
        }
        cout << "" << totalBytesTransferred << " Done" << endl;
        myfile.close();
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoCopy --
 *
 *      Copies an extent from a local disk to another local disk
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoCopy(void)
{
    uint32 srcFlags = VIXDISKLIB_FLAG_OPEN_READ_ONLY | VIXDISKLIB_FLAG_OPEN_SINGLE_LINK;
    VixDisk targetDisk(appGlobals.localConnection, appGlobals.diskPath, appGlobals.openFlags);
    VixDisk srcDisk(appGlobals.localConnection, appGlobals.srcPath, srcFlags);
    uint8 buf[VIXDISKLIB_BUF_SIZE];
    VixDiskLibSectorType numSectors;
    VixDiskLibSectorType startSector;
    VixDiskLibSectorType i;
    VixError vixError;
    
    numSectors = appGlobals.numSectors;
    startSector = appGlobals.startSector;

    while (numSectors)
    {
        
        VixDiskLibSectorType nsec = (numSectors >= VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE) ?
                                      VIXDISKLIB_BUF_SIZE/VIXDISKLIB_SECTOR_SIZE : numSectors;

        // Read from remote disk and copy it to local disk
        vixError = VixDiskLib_Read(srcDisk.Handle(),
                                   startSector,
                                   nsec, buf);
        CHECK_AND_THROW(vixError);

        vixError = VixDiskLib_Write(targetDisk.Handle(),
                                    startSector,
                                    nsec, buf);
        CHECK_AND_THROW(vixError);
        startSector += nsec;
        numSectors -= nsec;
    }
}

/*
 *--------------------------------------------------------------------------
 *
 * DoAttach --
 *
 *      Attaches the disk to specified parent disk
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */
static void
DoAttach(void)
{
    VixDisk parentDisk(appGlobals.localConnection, appGlobals.parentPath, appGlobals.openFlags);
    VixDisk childDisk(appGlobals.localConnection, appGlobals.diskPath, VIXDISKLIB_FLAG_OPEN_SINGLE_LINK);
    VixError vixError;
    
   	vixError = VixDiskLib_Attach(parentDisk.Handle(), childDisk.Handle());
   	CHECK_AND_THROW(vixError);
}



/*
 *--------------------------------------------------------------------------
 *
 * DoReadMetadata --
 *
 *      Reads metadata from a virtual disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoReadMetadata(void)
{
    size_t requiredLen;
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    VixError vixError = VixDiskLib_ReadMetadata(disk.Handle(),
                                                appGlobals.metaKey,
                                                NULL, 0, &requiredLen);
    if (vixError != VIX_OK && vixError != VIX_E_BUFFER_TOOSMALL) {
        THROW_ERROR(vixError);
    }
    std::vector <char> val(requiredLen);
    vixError = VixDiskLib_ReadMetadata(disk.Handle(),
                                       appGlobals.metaKey,
                                       &val[0],
                                       requiredLen,
                                       NULL);
    CHECK_AND_THROW(vixError);
    cout << appGlobals.metaKey << " = " << &val[0] << endl;
}


/*
 *--------------------------------------------------------------------------
 *
 * DoWriteMetadata --
 *
 *      Writes metadata in a virtual disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoWriteMetadata(void)
{
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    VixError vixError = VixDiskLib_WriteMetadata(disk.Handle(),
                                                 appGlobals.metaKey,
                                                 appGlobals.metaVal);
    CHECK_AND_THROW(vixError);
}


/*
 *--------------------------------------------------------------------------
 *
 * DoDumpMetadata --
 *
 *      Dumps all the metadata.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoDumpMetadata(void)
{
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    char *key;
    size_t requiredLen;

    VixError vixError = VixDiskLib_GetMetadataKeys(disk.Handle(),
                                                   NULL, 0, &requiredLen);
    if (vixError != VIX_OK && vixError != VIX_E_BUFFER_TOOSMALL) {
       THROW_ERROR(vixError);
    }
    std::vector<char> buf(requiredLen);
    vixError = VixDiskLib_GetMetadataKeys(disk.Handle(), &buf[0], requiredLen, NULL);
    CHECK_AND_THROW(vixError);
    key = &buf[0];

    while (*key) {
        vixError = VixDiskLib_ReadMetadata(disk.Handle(), key, NULL, 0,
                                           &requiredLen);
        if (vixError != VIX_OK && vixError != VIX_E_BUFFER_TOOSMALL) {
           THROW_ERROR(vixError);
        }
        std::vector <char> val(requiredLen);
        vixError = VixDiskLib_ReadMetadata(disk.Handle(), key, &val[0],
                                           requiredLen, NULL);
        CHECK_AND_THROW(vixError);
        cout << key << " = " << &val[0] << endl;
        key += (1 + strlen(key));
    }
}


/*
 *--------------------------------------------------------------------------
 *
 * DoDump --
 *
 *      Dumps the content of a virtual disk.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoDump(void)
{
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    uint8 buf[VIXDISKLIB_SECTOR_SIZE];
    VixDiskLibSectorType i;

    for (i = 0; i < appGlobals.numSectors; i++) {
        VixError vixError = VixDiskLib_Read(disk.Handle(),
                                            appGlobals.startSector + i,
                                            1, buf);
        CHECK_AND_THROW(vixError);
        DumpBytes(buf, sizeof buf, 16);
    }
}


/*
 *--------------------------------------------------------------------------
 *
 * BitCount --
 *
 *      Counts all the bits set in an int.
 *
 * Results:
 *      Number of bits set to 1.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static int
BitCount(int number)    // IN
{
    int bits = 0;
    while (number) {
        number = number & (number - 1);
        bits++;
    }
    return bits;
}


/*
 *----------------------------------------------------------------------
 *
 * DumpBytes --
 *
 *      Displays an array of n bytes.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DumpBytes(const unsigned char *buf,     // IN
          size_t n,                     // IN
          int step)                     // IN
{
   size_t lines = n / step;
   size_t i;

   for (i = 0; i < lines; i++) {
      int k, last;
      printf("%04" FMTSZ "x : ", i * step);
      for (k = 0; n != 0 && k < step; k++, n--) {
         printf("%02x ", buf[i * step + k]);
      }
      printf("  ");
      last = k;
      while (k --) {
         unsigned char c = buf[i * step + last - k - 1];
         if (c < ' ' || c >= 127) {
            c = '.';
         }
         printf("%c", c);
      }
      printf("\n");
   }
   printf("\n");
}


/*
 *----------------------------------------------------------------------
 *
 * CopyThread --
 *
 *       Copies a source disk to the given file.
 *
 * Results:
 *       0 if succeeded, 1 if not.
 *
 * Side effects:
 *      Creates a new disk; sets appGlobals.success to false if fails
 *
 *----------------------------------------------------------------------
 */

#ifdef _WIN32
#define TASK_OK 0
#define TASK_FAIL 1

static unsigned __stdcall
#else
#define TASK_OK ((void*)0)
#define TASK_FAIL ((void*)1)

static void *
#endif
CopyThread(void *arg)
{
   ThreadData *td = (ThreadData *)arg;

    try {
      VixDiskLibSectorType i;
      VixError vixError;
      uint8 buf[VIXDISKLIB_SECTOR_SIZE];

      for (i = 0; i < td->numSectors; i ++) {
         vixError = VixDiskLib_Read(td->srcHandle, i, 1, buf);
         CHECK_AND_THROW(vixError);
         vixError = VixDiskLib_Write(td->dstHandle, i, 1, buf);
         CHECK_AND_THROW(vixError);
      }

    } catch (const VixDiskLibErrWrapper& e) {
       cout << "CopyThread (" << td->dstDisk << ")Error: " << e.ErrorCode()
            <<" " << e.Description();
        appGlobals.success = FALSE;
        return TASK_FAIL;
    }

    cout << "CopyThread to " << td->dstDisk << " succeeded.\n";
    return TASK_OK;
}


/*
 *----------------------------------------------------------------------
 *
 * PrepareThreadData --
 *
 *      Open the source and destination disk for multi threaded copy.
 *
 * Results:
 *      Fills in ThreadData in td.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
PrepareThreadData(VixDiskLibConnection &dstConnection,
                  ThreadData &td)
{
   VixError vixError;
   VixDiskLibCreateParams createParams;
   VixDiskLibInfo *info = NULL;
   char *tmpDir;

#ifdef _WIN32
   tmpDir = _tempnam("c:\\", "test");
#else
   tmpDir = tempnam("/tmp", "test");
#endif
   td.dstDisk = tmpDir;
   free(tmpDir);

   vixError = VixDiskLib_Open(appGlobals.connection,
                              appGlobals.diskPath,
                              appGlobals.openFlags,
                              &td.srcHandle);
   CHECK_AND_THROW(vixError);

   vixError = VixDiskLib_GetInfo(td.srcHandle, &info);
   CHECK_AND_THROW(vixError);
   td.numSectors = info->capacity;
   VixDiskLib_FreeInfo(info);

   createParams.adapterType = VIXDISKLIB_ADAPTER_SCSI_BUSLOGIC;
   createParams.capacity = td.numSectors;
   createParams.diskType = VIXDISKLIB_DISK_SPLIT_SPARSE;
   createParams.hwVersion = VIXDISKLIB_HWVERSION_WORKSTATION_5;

   vixError = VixDiskLib_Create(dstConnection, td.dstDisk.c_str(),
                                &createParams, NULL, NULL);
   CHECK_AND_THROW(vixError);

   vixError = VixDiskLib_Open(dstConnection, td.dstDisk.c_str(), 0,
                              &td.dstHandle);
   CHECK_AND_THROW(vixError);
}


/*
 *----------------------------------------------------------------------
 *
 * DoTestMultiThread --
 *
 *      Starts a given number of threads, each of which will copy the
 *      source disk to a temp. file.
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DoTestMultiThread(void)
{
   VixDiskLibConnectParams cnxParams = { 0 };
   VixDiskLibConnection dstConnection;
   VixError vixError;
   vector<ThreadData> threadData(appGlobals.numThreads);
   int i;

   vixError = VixDiskLib_Connect(&cnxParams, &dstConnection);
   CHECK_AND_THROW(vixError);

#ifdef _WIN32
   vector<HANDLE> threads(appGlobals.numThreads);

   for (i = 0; i < appGlobals.numThreads; i++) {
      unsigned int threadId;

      PrepareThreadData(dstConnection, threadData[i]);
      threads[i] = (HANDLE)_beginthreadex(NULL, 0, &CopyThread,
                                          (void*)&threadData[i], 0, &threadId);
   }
   WaitForMultipleObjects(appGlobals.numThreads, &threads[0], TRUE, INFINITE);
#else
   vector<pthread_t> threads(appGlobals.numThreads);

   for (i = 0; i < appGlobals.numThreads; i++) {
      PrepareThreadData(dstConnection, threadData[i]);
      pthread_create(&threads[i], NULL, &CopyThread, (void*)&threadData[i]);
   }
   for (i = 0; i < appGlobals.numThreads; i++) {
      void *hlp;
      pthread_join(threads[i], &hlp);
   }
#endif

   for (i = 0; i < appGlobals.numThreads; i++) {
      VixDiskLib_Close(threadData[i].srcHandle);
      VixDiskLib_Close(threadData[i].dstHandle);
      VixDiskLib_Unlink(dstConnection, threadData[i].dstDisk.c_str());
   }
   VixDiskLib_Disconnect(dstConnection);
   if (!appGlobals.success) {
      THROW_ERROR(VIX_E_FAIL);
   }
}


/*
 *----------------------------------------------------------------------
 *
 * CloneProgress --
 *
 *      Callback for the clone function.
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static Bool
CloneProgressFunc(void * /*progressData*/,      // IN
                  int percentCompleted)         // IN
{
   //cout << "Cloning : " << percentCompleted << "% Done" << "\r";
   cout << "Cloning : " << percentCompleted << "% Done" << endl;
   return TRUE;
}


/*
 *----------------------------------------------------------------------
 *
 * DoClone --
 *
 *      Clones a local disk (possibly to an ESX host).
 *
 * Results:
 *      None.
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DoClone(void)
{
   VixDiskLibConnection dummyConnection;
   VixDiskLibConnectParams cnxParams = { 0 };
   VixError vixError = VixDiskLib_Connect(&cnxParams, &dummyConnection);
   CHECK_AND_THROW(vixError);

   /*
    *  Note : These createParams are ignored for remote case
   */
   
   VixDiskLibCreateParams createParams;
   createParams.adapterType = appGlobals.adapterType;
   createParams.capacity = appGlobals.mbSize * 2048;
   createParams.diskType = VIXDISKLIB_DISK_MONOLITHIC_SPARSE;
   createParams.hwVersion = VIXDISKLIB_HWVERSION_WORKSTATION_5;

   if (!strcmp(appGlobals.source, "remote"))
   {
	   vixError = VixDiskLib_Clone(	dummyConnection,		//destConnection
									appGlobals.diskPath,	//destPath
									appGlobals.connection,	//srcConnection
									appGlobals.srcPath,		//srcConnection
									&createParams,
									CloneProgressFunc,
									NULL,					//clientData
									TRUE);					//doOverWrite
   }
   else
   {
	   vixError = VixDiskLib_Clone(appGlobals.connection,	//destConnection
								   appGlobals.diskPath,		//destPath
								   dummyConnection,			//srcConnection
								   appGlobals.srcPath,		//srcConnection
								   &createParams,
								   CloneProgressFunc,
								   NULL,					//clientData
								   TRUE);					//doOverWrite
   }
   VixDiskLib_Disconnect(dummyConnection);
   CHECK_AND_THROW(vixError);
   cout << "\n Done" << "\n";
}

/*
 *----------------------------------------------------------------------
 *
 * PrintStat --
 *
 *      Print performance statistics for read/write benchmarks.
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
PrintStat(bool read,            // IN
          struct timeval start, // IN
          struct timeval end,   // IN
          uint32 numSectors)    // IN
{
   uint64 elapsed;
   uint32 speed;

   elapsed = ((uint64)end.tv_sec * 1000000 + end.tv_usec -
              ((uint64)start.tv_sec * 1000000 + start.tv_usec)) / 1000;
   if (elapsed == 0) {
      elapsed = 1;
   }
   speed = (1000 * VIXDISKLIB_SECTOR_SIZE * (uint64)numSectors) / (1024 * 1024 * elapsed);
   printf("%s %d MBytes in %d msec (%d MBytes/sec)\n", read ? "Read" : "Wrote",
          (uint32)(numSectors /(2048)), (uint32)elapsed, speed);
}


/*
 *----------------------------------------------------------------------
 *
 * InitBuffer --
 *
 *      Fill an array of uint32 with random values, to defeat any
 *      attempts to compress it.
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
InitBuffer(uint32 *buf,     // OUT
           uint32 numElems) // IN
{
   int i;

   srand(time(NULL));

   for (i = 0; i < numElems; i++) {
      buf[i] = (uint32)rand();
   }
}


/*
 *----------------------------------------------------------------------
 *
 * DoRWBench --
 *
 *      Perform read/write benchmarks according to settings in
 *      appGlobals. Note that a write benchmark will destroy the data
 *      in the target disk.
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DoRWBench(bool read) // IN
{
   VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
   size_t bufSize;
   uint8 *buf;
   VixDiskLibInfo *info;
   VixError err;
   uint32 maxOps, i;
   uint32 bufUpdate;
   struct timeval start, end, total;

   if (appGlobals.bufSize == 0) {
      appGlobals.bufSize = DEFAULT_BUFSIZE;
   }
   bufSize = appGlobals.bufSize * VIXDISKLIB_SECTOR_SIZE;

   buf = new uint8[bufSize];
   if (!read) {
      InitBuffer((uint32*)buf, bufSize / sizeof(uint32));
   }

   err = VixDiskLib_GetInfo(disk.Handle(), &info);
   if (VIX_FAILED(err)) {
      delete [] buf;
      throw VixDiskLibErrWrapper(err, __FILE__, __LINE__);
   }

   maxOps = info->capacity / appGlobals.bufSize;
   VixDiskLib_FreeInfo(info);

   printf("Processing %d buffers of %d bytes.\n", maxOps, (uint32)bufSize);

   gettimeofday(&total, NULL);
   start = total;
   bufUpdate = 0;
   for (i = 0; i < maxOps; i++) {
      VixError vixError;

      if (read) {
         vixError = VixDiskLib_Read(disk.Handle(),
                                    i * appGlobals.bufSize,
                                    appGlobals.bufSize, buf);
      } else {
         vixError = VixDiskLib_Write(disk.Handle(),
                                     i * appGlobals.bufSize,
                                     appGlobals.bufSize, buf);

      }
      if (VIX_FAILED(vixError)) {
         delete [] buf;
         throw VixDiskLibErrWrapper(vixError, __FILE__, __LINE__);
      }

      bufUpdate += appGlobals.bufSize;
      if (bufUpdate >= BUFS_PER_STAT) {
         gettimeofday(&end, NULL);
         PrintStat(read, start, end, bufUpdate);
         start = end;
         bufUpdate = 0;
      }
   }
   gettimeofday(&end, NULL);
   PrintStat(read, total, end, appGlobals.bufSize * maxOps);
   delete [] buf;
}


/*
 *----------------------------------------------------------------------
 *
 * DoCheckRepair --
 *
 *      Check a sparse disk for internal consistency.
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DoCheckRepair(Bool repair)
{
   VixError err;

   err = VixDiskLib_CheckRepair(appGlobals.connection, appGlobals.diskPath,
                                repair);
   if (VIX_FAILED(err)) {
      throw VixDiskLibErrWrapper(err, __FILE__, __LINE__);
   }
}

/*
 *----------------------------------------------------------------------
 *
 * DoMount--
 *
 *      Mount a virtual disk of the virtual disk of the remote host
 *      locally
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DoMount()
{
      VixError err;
      VixDiskSetHandle *handle;
      VixVolumeHandle *volumeHandles;
      size_t numberOfVolumes = 0;
      VixOsInfo *info = NULL;
      VixDiskSetInfo* diskSetInfo = NULL;
  
      cout << "Enter DoMount" << endl;
      cout << "Disk Paths File: " << appGlobals.diskPath << endl;
      cout << "Mount Points File: " << appGlobals.mountpointsfile << endl;
    
      std::vector<std::string> lines;
      std::ifstream diskpaths_file(appGlobals.diskPath);
      std::ofstream mountpoints_file(appGlobals.mountpointsfile);
      if(diskpaths_file.is_open())
      {
          std::string line;
          while(getline(diskpaths_file, line))
          {
              lines.push_back(line);
          }
      }   
      diskpaths_file.close();
     
      char** diskPaths = (char**) calloc( 2, sizeof(char*) );
      if (diskPaths == NULL)
            exit(-1);
 
      for (std::vector<std::string>::iterator it = lines.begin(); it != lines.end(); ++it)
      {
          diskPaths[0] = (char*)((*it).c_str());     
          cout << "Mounting Disk: " << diskPaths[0] << endl;
          VixDisks disks(appGlobals.connection, (const char**)diskPaths, 1, appGlobals.openFlags);
          VixMntapi_GetDiskSetInfo(disks.Handle(), &diskSetInfo);
          mountpoints_file << diskPaths[0] << ": ";
          cout <<  "diskSetInfo->mountPath: " << diskSetInfo->mountPath << endl;
          mountpoints_file << diskSetInfo->mountPath;
           
          if (appGlobals.diskonlymount != 1) 
          {
              cout << "Mounting Volumes" << endl;
              err = VixMntapi_GetVolumeHandles(disks.Handle(), &numberOfVolumes, &volumeHandles);
              CHECK_AND_THROW(err);
              for (size_t i = 0; i < numberOfVolumes; i++)
              {
                  err = VixMntapi_MountVolume(volumeHandles[i], FALSE);
                  CHECK_AND_THROW(err);
     
                  VixVolumeInfo *volumeInfo = NULL;
                  err = VixMntapi_GetVolumeInfo(volumeHandles[i], &volumeInfo);
                  CHECK_AND_THROW(err);
                 
                  if (volumeInfo->symbolicLink != NULL)
                        mountpoints_file << ";" << volumeInfo->symbolicLink;
                        cout <<  "volumeInfo->symbolicLink: " << volumeInfo->symbolicLink << endl;
                  VixMntapi_FreeVolumeInfo(volumeInfo);
                  volumeInfo = NULL;
              }
          }
          mountpoints_file << "\n";
     
          mountpoints_file.close();
          diskpaths_file.close();
          printf("Pausing the process until it is resumed\n");
          std::cout.flush();
     
          raise(SIGSTOP);  
 
          if (appGlobals.diskonlymount != 1) 
          {
              cout << "Dismounting Volumes" << endl;
              for (size_t i = 0; i < numberOfVolumes; i++)
              {    
                    err = VixMntapi_DismountVolume(volumeHandles[i], false);
                    CHECK_AND_THROW(err);        
              }
              VixMntapi_FreeVolumeHandles(volumeHandles);    
          }
          VixMntapi_FreeDiskSetInfo(diskSetInfo);
          free(diskPaths);
          cout << "Exit DoMount" << endl;
          break; // TODO: For now we support only one disk mount. Fix it
      }
}
 

/*
 *----------------------------------------------------------------------
 *
 * DoUnmount--
 *
 *      Unmount a virtual disk of the virtual disk of the remote host
 *      locally
 *
 * Results:
 *      None
 *
 * Side effects:
 *      None.
 *
 *----------------------------------------------------------------------
 */

static void
DoUnmount()
{
   VixError err;
   VixDiskSetHandle *handle;
   const char *diskPaths[] = {appGlobals.diskPath, };
   VixVolumeHandle *volumeHandles;
   size_t numberOfVolumes;
   VixOsInfo *info = NULL;

   VixDisks disks(appGlobals.connection, diskPaths, 1, appGlobals.openFlags);

   err = VixMntapi_GetVolumeHandles(disks.Handle(), &numberOfVolumes, &volumeHandles);
   CHECK_AND_THROW(err);

   for (size_t i = 0; i < numberOfVolumes; i++) 
   {
       VixVolumeHandle volumeHandle = volumeHandles[i];

       err = VixMntapi_DismountVolume(volumeHandle, false);
       CHECK_AND_THROW(err);
   }
   VixMntapi_FreeVolumeHandles(volumeHandles);
}

 /*--------------------------------------------------------------------------
 *
 * DoSpaceForClone --
 *
 *      Computes the space required to clone to the given disktype.
 *
 * Results:
 *      Space Needed for Clone in Bytes.
 *
 * Side effects:
 *      None.
 *
 *--------------------------------------------------------------------------
 */

static void
DoSpaceForClone(void)
{
    VixDisk disk(appGlobals.connection, appGlobals.diskPath, appGlobals.openFlags);
    VixDiskLibDiskType disk_type = VIXDISKLIB_DISK_MONOLITHIC_FLAT;
    if (strcmp(appGlobals.diskType, "flatMonolithic") == 0 
    	|| strcmp(appGlobals.diskType, "thick") == 0 
    	|| strcmp(appGlobals.diskType, "eagerZeroedThick") == 0
    	|| strcmp(appGlobals.diskType, "preallocated") == 0 )
    	disk_type = VIXDISKLIB_DISK_MONOLITHIC_FLAT;
    else if (strcmp(appGlobals.diskType, "flatMonolithic") == 0 
    		 || strcmp(appGlobals.diskType, "seSparse") == 0
    		 || strcmp(appGlobals.diskType, "sparseMonolithic") == 0
    		 || strcmp(appGlobals.diskType, "thin") == 0)
    	disk_type = VIXDISKLIB_DISK_MONOLITHIC_SPARSE;

	uint64 spaceNeeded = 0;
    VixError vixError = VixDiskLib_SpaceNeededForClone(disk.Handle(), disk_type,  &spaceNeeded);
    CHECK_AND_THROW(vixError);

	cout << "" << spaceNeeded << " Bytes Required for Cloning" << endl;
}