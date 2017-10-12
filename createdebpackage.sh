#!/usr/bin/env bash


if ["$UID" != "0"]
    then echo "Please run as root/sudo"
exit
fi
set - u
#set -e

ROOTDIR = /tmp / workloadmanager
SRC = /tmp / workloadmanager / data
CONTROL = /tmp / workloadmanager / control
DEBIAN =${CONTROL} / DEBIAN
USR =${SRC} / usr

rm - rf ${ROOTDIR}
# rm -rf ${DIST}

mkdir - p ${USR}/
mkdir - p ${DEBIAN}/

cp - r debian / workloadmanager / usr / * ${USR}/
cp - r etc ${SRC}/
pushd debian / workloadmanager
cp - r DEBIAN / * ${DEBIAN}/
popd

echo 2.0 > ${ROOTDIR} / debian - binary

# set the permission
chmod 0755 `find ${SRC} - type d`
chmod go - w `find ${SRC} - type f`
chown - R root: root ${SRC}/

let SIZE = `du - s ${SRC} | sed s'/\s\+.*//'`+8
pushd ${SRC}/
tar czf ${ROOTDIR} / data.tar.gz[a - z]*
popd
sed s"/SIZE/${SIZE}/" - i ${DEBIAN} / control
pushd ${DEBIAN}
tar czf ${ROOTDIR} / control.tar.gz *
popd

pushd ${ROOTDIR}
chmod 0755 `find ${SRC} - type d`
chmod go - w `find ${SRC} - type f`
chown - R root: root ${ROOTDIR}/
ar r ${ROOTDIR} / workloadmanager - 1.deb debian - binary control.tar.gz data.tar.gz
popd
mv ${ROOTDIR} / workloadmanager - 1.deb .
