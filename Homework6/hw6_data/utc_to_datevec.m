function dv = utc_to_datevec(utc, tz)
% dv = utc_to_datevec(utc, tz)
%   Convert UTC unix timestamp to datevec
%   tz = time zone in hours (i.e., -5 is EST with no daylight savings)
%   (Does not handle automatic DST conversion)

if (nargin < 2), tz = 0; end
dn = datenum(1970,1,1) + utc/(24*60*60) + tz/24;
dv = datevec(dn);