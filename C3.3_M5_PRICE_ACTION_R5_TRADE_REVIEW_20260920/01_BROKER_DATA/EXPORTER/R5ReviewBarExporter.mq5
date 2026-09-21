#property strict
#property version "1.000"

input string InpOutputTag="AUGUST";

int g_m5=INVALID_HANDLE;
int g_m15=INVALID_HANDLE;
datetime g_last_m5=0;
datetime g_last_m15=0;

bool WriteClosedBar(const ENUM_TIMEFRAMES timeframe,const int handle)
{
   MqlRates rates[];
   ArraySetAsSeries(rates,true);
   if(CopyRates(_Symbol,timeframe,1,1,rates)!=1) return false;
   FileWrite(handle,(long)rates[0].time,
      TimeToString(rates[0].time,TIME_DATE|TIME_MINUTES|TIME_SECONDS),
      DoubleToString(rates[0].open,_Digits),DoubleToString(rates[0].high,_Digits),
      DoubleToString(rates[0].low,_Digits),DoubleToString(rates[0].close,_Digits),
      (long)rates[0].tick_volume,rates[0].spread,(long)rates[0].real_volume);
   return true;
}

int OnInit()
{
   const string folder="R5_TRADE_REVIEW\\";
   FolderCreate("R5_TRADE_REVIEW",FILE_COMMON);
   g_m5=FileOpen(folder+InpOutputTag+"_M5.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   g_m15=FileOpen(folder+InpOutputTag+"_M15.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(g_m5==INVALID_HANDLE || g_m15==INVALID_HANDLE)
   {
      Print("R5_REVIEW_EXPORT_ERROR|tag=",InpOutputTag,"|code=",GetLastError());
      return INIT_FAILED;
   }
   FileWrite(g_m5,"time_epoch","time","open","high","low","close","tick_volume","spread_points","real_volume");
   FileWrite(g_m15,"time_epoch","time","open","high","low","close","tick_volume","spread_points","real_volume");
   Print("R5_REVIEW_EXPORT_START|tag=",InpOutputTag,"|symbol=",_Symbol);
   return INIT_SUCCEEDED;
}

void OnTick()
{
   const datetime current_m5=iTime(_Symbol,PERIOD_M5,0);
   if(current_m5>0 && current_m5!=g_last_m5)
   {
      WriteClosedBar(PERIOD_M5,g_m5);
      g_last_m5=current_m5;
   }
   const datetime current_m15=iTime(_Symbol,PERIOD_M15,0);
   if(current_m15>0 && current_m15!=g_last_m15)
   {
      WriteClosedBar(PERIOD_M15,g_m15);
      g_last_m15=current_m15;
   }
}

void OnDeinit(const int reason)
{
   if(g_m5!=INVALID_HANDLE){FileFlush(g_m5);FileClose(g_m5);}
   if(g_m15!=INVALID_HANDLE){FileFlush(g_m15);FileClose(g_m15);}
   Print("R5_REVIEW_EXPORT_END|tag=",InpOutputTag,"|reason=",reason);
}
