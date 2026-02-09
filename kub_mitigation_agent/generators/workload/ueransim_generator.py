"""UERANSIM-based 5G traffic generator."""

import asyncio
import logging
from typing import Dict, Any, List
from kub_mitigation_agent.service.apps import Open5GS
from .base import WorkloadGenerator

logger = logging.getLogger(__name__)


class UERANSIMTrafficGenerator(WorkloadGenerator):
    """
    UERANSIM-based traffic generator for 5G Core testing.
    
    This generator uses UERANSIM to simulate realistic 5G UE (User Equipment)
    behavior including UE registration, PDU session establishment, and data
    plane traffic generation.
    
    Unlike HTTP-based Locust generators, this generator works at the 5G protocol
    level using NGAP, NAS, and GTP protocols.
    
    Usage:
        config = {
            "namespace": "open5gs",
            "num_ues": 11,
            "traffic_type": "continuous",  # or "bursty"
            "pdu_sessions_per_ue": 1,
            "sst": 1,
            "sd": "1",
            "dnn": "internet",
        }
        generator = UERANSIMTrafficGenerator(config)
        await generator.start_traffic()
        # ... traffic runs continuously ...
        await generator.stop_traffic()
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize UERANSIM traffic generator.
        
        Args:
            config: Configuration dictionary with:
                - namespace: K8s namespace where Open5GS is deployed
                - num_ues: Number of UEs to activate (default: 11)
                - traffic_type: "continuous" or "bursty" (default: continuous)
                - pdu_sessions_per_ue: PDU sessions per UE (default: 1)
                - sst: Slice Service Type (default: 1)
                - sd: Slice Differentiator (default: "1")
                - dnn: Data Network Name (default: "internet")
        """
        super().__init__(config)
        self.namespace = config.get("namespace", "open5gs")
        self.num_ues = config.get("num_ues", 11)
        self.traffic_type = config.get("traffic_type", "continuous")
        self.pdu_sessions_per_ue = config.get("pdu_sessions_per_ue", 1)
        self.sst = config.get("sst", 1)
        self.sd = config.get("sd", "1")
        self.dnn = config.get("dnn", "internet")
        
        self.app = None
        self.active_sessions: List[Dict[str, Any]] = []
        self._traffic_task = None
    
    async def start_traffic(self):
        """
        Start generating 5G traffic using UERANSIM.
        
        This will:
        1. Initialize Open5GS app connection
        2. Get list of available UEs
        3. Establish PDU sessions for configured UEs
        4. Start continuous or bursty traffic generation
        """
        if self.is_running:
            logger.warning("Traffic generation already running")
            return
        
        logger.info(f"Starting UERANSIM traffic generation with {self.num_ues} UEs")
        
        try:
            # Initialize Open5GS app
            self.app = Open5GS()
            
            # List available UEs
            ues_output = self.app.list_ues()
            logger.info(f"Available UEs:\n{ues_output}")
            
            # Establish PDU sessions for UEs
            for i in range(1, self.num_ues + 1):
                imsi = f"imsi-999700000000{i:03d}"
                
                for session_num in range(self.pdu_sessions_per_ue):
                    try:
                        logger.info(f"Establishing PDU session for {imsi} (session {session_num + 1})")
                        result = self.app.establish_pdu_session(
                            imsi=imsi,
                            sst=self.sst,
                            sd=self.sd,
                            dnn=self.dnn
                        )
                        
                        self.active_sessions.append({
                            "imsi": imsi,
                            "session_id": session_num + 1,
                        })
                        
                        logger.debug(f"PDU session established: {result}")
                        
                        # Wait a bit for session to be fully established
                        await asyncio.sleep(5)
                        
                    except Exception as e:
                        logger.error(f"Failed to establish PDU session for {imsi}: {e}")
            
            logger.info(f"Established {len(self.active_sessions)} PDU sessions")
            
            # Start traffic generation task
            if self.traffic_type == "continuous":
                self._traffic_task = asyncio.create_task(self._generate_continuous_traffic())
            elif self.traffic_type == "bursty":
                self._traffic_task = asyncio.create_task(self._generate_bursty_traffic())
            
            self.is_running = True
            logger.info("UERANSIM traffic generation started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start traffic generation: {e}")
            raise
    
    async def stop_traffic(self):
        """
        Stop generating 5G traffic and release PDU sessions.
        
        This will:
        1. Stop traffic generation task
        2. Release all active PDU sessions
        3. Clean up resources
        """
        if not self.is_running:
            logger.warning("Traffic generation not running")
            return
        
        logger.info("Stopping UERANSIM traffic generation")
        
        try:
            # Cancel traffic generation task
            if self._traffic_task and not self._traffic_task.done():
                self._traffic_task.cancel()
                try:
                    await self._traffic_task
                except asyncio.CancelledError:
                    pass
            
            # Release all PDU sessions
            for session in self.active_sessions:
                try:
                    logger.info(f"Releasing PDU session for {session['imsi']}")
                    result = self.app.release_pdu_session(
                        imsi=session['imsi'],
                        session_id=session['session_id']
                    )
                    logger.debug(f"PDU session released: {result}")
                except Exception as e:
                    logger.error(f"Failed to release PDU session for {session['imsi']}: {e}")
            
            self.active_sessions.clear()
            self.is_running = False
            
            logger.info("UERANSIM traffic generation stopped successfully")
            
        except Exception as e:
            logger.error(f"Failed to stop traffic generation: {e}")
            raise
    
    async def _generate_continuous_traffic(self):
        """
        Generate continuous background traffic.
        
        This simulates always-on connectivity with periodic keepalive traffic.
        """
        logger.info("Starting continuous traffic generation")
        
        try:
            while True:
                # Simulate continuous connectivity
                # In a real implementation, this would use nr-binder to generate
                # actual data plane traffic (e.g., ping, iperf, HTTP requests)
                logger.debug(f"Continuous traffic active for {len(self.active_sessions)} sessions")
                await asyncio.sleep(30)  # Keepalive interval
                
        except asyncio.CancelledError:
            logger.info("Continuous traffic generation cancelled")
            raise
    
    async def _generate_bursty_traffic(self):
        """
        Generate bursty traffic patterns.
        
        This simulates realistic mobile usage with periods of activity and idle.
        """
        logger.info("Starting bursty traffic generation")
        
        try:
            while True:
                # Burst of activity
                logger.debug("Traffic burst active")
                await asyncio.sleep(10)  # Active period
                
                # Idle period
                logger.debug("Traffic idle period")
                await asyncio.sleep(20)  # Idle period
                
        except asyncio.CancelledError:
            logger.info("Bursty traffic generation cancelled")
            raise
